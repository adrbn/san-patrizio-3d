// Command find-token brute-forces the correct tokenP1 against Apple's live
// C3MM endpoint.
//
// Background: tokenP1 is a static secret embedded in the GeoServices binary.
// On modern macOS that binary lives inside the merged dyld shared cache, where
// the string that historically sat next to it is ambiguous. dump_token_candidates.sh
// emits every plausible candidate; this tool signs a real C3MM metadata request
// with each and keeps the one Apple accepts (HTTP 200), then writes config.json.
//
// Usage:
//
//	go run ./cmd/find-token [candidates_file]
//
// candidates_file defaults to ./token_candidates.txt
package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"os"
	"strconv"

	"github.com/retroplasma/flyover-reverse-engineering/pkg/fly"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mps"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mps/auth"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mps/config"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mth"
)

// Probe point. Override with FT_LAT / FT_LON env vars.
var probeLat, probeLon = 34.007603, -118.499741

var l = os.Stderr

func main() {
	candFile := "./token_candidates.txt"
	if len(os.Args) > 1 {
		candFile = os.Args[1]
	}
	if v := os.Getenv("FT_LAT"); v != "" {
		probeLat, _ = strconv.ParseFloat(v, 64)
	}
	if v := os.Getenv("FT_LON"); v != "" {
		probeLon, _ = strconv.ParseFloat(v, 64)
	}

	cache := mps.Cache{Enabled: true, Directory: "./cache"}
	if err := cache.Init(); err != nil {
		die(err)
	}
	cfg, err := config.FromJSONFile("./config.json")
	if err != nil {
		die(err)
	}
	if cfg.ResourceManifestURL == "" {
		die(errors.New("config.json: resourceManifestURL is empty"))
	}

	ctx, err := mps.Init(cache, cfg)
	if err != nil {
		die(fmt.Errorf("mps.Init: %w", err))
	}
	am, err := fly.GetAltitudeManifest(cache, ctx.ResourceManifest)
	if err != nil {
		die(fmt.Errorf("altitude manifest: %w", err))
	}

	place, err := findPlace(am, probeLat, probeLon)
	if err != nil {
		die(err)
	}
	fmt.Fprintf(l, "probe region=%d version=%d (%s)\n", place.Region, place.Version, place.Name)

	prefix, err := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3MM_1)
	if err != nil {
		die(err)
	}
	probeURL := fmt.Sprintf("%s?style=%d&v=%d&part=0&region=%d",
		prefix, mps.ResourceManifest_StyleConfig_C3MM_1, place.Version, place.Region)

	cands, err := readCandidates(candFile)
	if err != nil {
		die(err)
	}

	sid := ctx.AuthContext.Session.ID
	tokenP2 := ctx.ResourceManifest.GetTokenP2()

	// Diagnostic matrix: with the first candidate (assumed valid token), probe
	// the different tile styles/schemes to see which still serve data.
	if len(cands) > 0 {
		tok := cands[0]
		c3m, _ := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3M)
		c3mm2, _ := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3MM_2)
		x, y := mth.LatLonToTileTMS(20, probeLat, probeLon)
		yn := mth.TileCountPerAxis(20) - 1 - y
		diag := []struct{ label, url string }{
			{"C3MM_1 s14 part0", probeURL},
			{"C3MM_2 s52 z20 h0", fmt.Sprintf("%s?style=52&v=%d&region=%d&x=%d&y=%d&z=20&h=0", c3mm2, place.Version, place.Region, x, yn)},
			{"C3M   s15 z20 h0", fmt.Sprintf("%s?style=15&v=%d&region=%d&x=%d&y=%d&z=20&h=0", c3m, place.Version, place.Region, x, yn)},
			{"C3M   s15 z20 h1", fmt.Sprintf("%s?style=15&v=%d&region=%d&x=%d&y=%d&z=20&h=1", c3m, place.Version, place.Region, x, yn)},
			{"C3M   s15 z19 h0", fmt.Sprintf("%s?style=15&v=%d&region=%d&x=%d&y=%d&z=19&h=0", c3m, place.Version, place.Region, x/2, yn/2)},
		}
		fmt.Fprintln(l, "--- diagnostic (style matrix, authentic token) ---")
		for _, d := range diag {
			su, e := auth.AuthURL(d.url, sid, tok, tokenP2)
			if e != nil {
				continue
			}
			st, ct, head8 := getHead(su)
			fmt.Fprintf(l, "  %-18s -> HTTP %d  %-26s first: %q\n", d.label, st, ct, head8)
		}
		fmt.Fprintln(l, "---")
	}

	fmt.Fprintf(l, "testing %d candidate(s) against %s\n\n", len(cands), prefix)

	for i, cand := range cands {
		authURL, err := auth.AuthURL(probeURL, sid, cand, tokenP2)
		if err != nil {
			continue
		}
		status, ctype, err := head(authURL)
		mark := "·"
		switch {
		case err != nil:
			mark = "!"
		case status == 200 && ctype != "image/jpeg":
			fmt.Fprintf(l, "\n[%d] tokenP1 (%d chars) -> HTTP 200  ✔ MATCH\n", i, len(cand))
			writeConfig(cfg.ResourceManifestURL, cand)
			fmt.Fprintln(l, "config.json updated. Run: ./run_san_patrizio.sh")
			return
		case status == 200 && ctype == "image/jpeg":
			mark = "j" // authenticated OK but no C3MM here (jpeg placeholder) — token is still valid!
			fmt.Fprintf(l, "\n[%d] tokenP1 (%d chars) -> HTTP 200 (jpeg placeholder) ✔ token valid\n", i, len(cand))
			writeConfig(cfg.ResourceManifestURL, cand)
			fmt.Fprintln(l, "config.json updated. Run: ./run_san_patrizio.sh")
			return
		case status == 403:
			mark = "✗"
		default:
			mark = fmt.Sprintf("%d", status)
		}
		fmt.Fprintf(l, "%s", mark)
		if (i+1)%50 == 0 {
			fmt.Fprintf(l, " %d\n", i+1)
		}
	}
	fmt.Fprintln(l, "\n\nno candidate accepted by Apple (all 403).")
	fmt.Fprintln(l, "Fallback: ./scripts/get_config.sh  (downloads the 2017 SDK, ~2 GB)")
	os.Exit(1)
}

func head(url string) (int, string, error) {
	res, err := http.Get(url)
	if err != nil {
		return 0, "", err
	}
	defer res.Body.Close()
	return res.StatusCode, res.Header.Get("content-type"), nil
}

// findPlace mirrors export-obj's nearest-trigger selection.
func findPlace(am fly.AltitudeManifest, lat, lon float64) (fly.Trigger, error) {
	minDist, minPlace := math.Inf(1), fly.Trigger{}
	for _, v := range am.Triggers {
		dist := math.Sqrt(math.Pow(lat-v.Lat, 2) + math.Pow(lon-v.Lon, 2))
		if dist <= v.Radius && dist < minDist {
			minDist, minPlace = dist, v
		}
	}
	if math.IsInf(minDist, 1) {
		return fly.Trigger{}, errors.New("no Flyover trigger covers the probe point")
	}
	return minPlace, nil
}

func readCandidates(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w (run scripts/dump_token_candidates.sh first)", path, err)
	}
	defer f.Close()
	seen := map[string]bool{}
	var out []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1024), 1024*1024)
	for sc.Scan() {
		s := sc.Text()
		if len(s) < 8 || len(s) > 128 || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out, sc.Err()
}

func writeConfig(rmURL, tokenP1 string) {
	b, _ := json.MarshalIndent(map[string]string{
		"resourceManifestURL": rmURL,
		"tokenP1":             tokenP1,
	}, "", "  ")
	if err := os.WriteFile("./config.json", append(b, '\n'), 0644); err != nil {
		die(err)
	}
}

func die(err error) {
	fmt.Fprintln(l, "error:", err)
	os.Exit(1)
}

// getHead fetches url and returns status, content-type, and first 12 bytes.
func getHead(u string) (int, string, string) {
	res, err := http.Get(u)
	if err != nil {
		return -1, err.Error(), ""
	}
	defer res.Body.Close()
	buf := make([]byte, 12)
	n, _ := res.Body.Read(buf)
	return res.StatusCode, res.Header.Get("content-type"), string(buf[:n])
}
