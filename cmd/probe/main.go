// Command probe authenticates and reports HTTP status for C3MM/C3M requests at
// a given lat/lon, to diagnose whether Flyover data is served there and whether
// the URL scheme still matches the code's expectations.
//
//	go run ./cmd/probe [lat] [lon] [zoom]
package main

import (
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

func main() {
	lat, lon, zoom := 34.007603, -118.499741, 20
	if len(os.Args) > 2 {
		lat, _ = strconv.ParseFloat(os.Args[1], 64)
		lon, _ = strconv.ParseFloat(os.Args[2], 64)
	}
	if len(os.Args) > 3 {
		zoom, _ = strconv.Atoi(os.Args[3])
	}

	cache := mps.Cache{Enabled: true, Directory: "./cache"}
	must(cache.Init())
	cfg, err := config.FromJSONFile("./config.json")
	must(err)
	ctx, err := mps.Init(cache, cfg)
	must(err)
	am, err := fly.GetAltitudeManifest(cache, ctx.ResourceManifest)
	must(err)

	place := nearest(am, lat, lon)
	fmt.Printf("point %.5f,%.5f -> trigger %s region=%d version=%d\n",
		lat, lon, place.Name, place.Region, place.Version)

	c3mmPfx, _ := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3MM_1)
	c3mm2Pfx, _ := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3MM_2)
	c3mPfx, _ := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3M)

	x, y := mth.LatLonToTileTMS(zoom, lat, lon)
	yn := mth.TileCountPerAxis(zoom) - 1 - y

	sid := ctx.AuthContext.Session.ID
	p2 := ctx.ResourceManifest.GetTokenP2()
	sign := func(u string) string { s, _ := auth.AuthURL(u, sid, string(ctx.AuthContext.TokenP1), p2); return s }

	probes := []struct{ label, url string }{
		{"C3MM_1 part0", fmt.Sprintf("%s?style=14&v=%d&part=0&region=%d", c3mmPfx, place.Version, place.Region)},
		{"C3MM_1 part0 no-v", fmt.Sprintf("%s?style=14&part=0&region=%d", c3mmPfx, place.Region)},
		{"C3MM_2 tile", fmt.Sprintf("%s?style=52&v=%d&region=%d&x=%d&y=%d&z=%d&h=0", c3mm2Pfx, place.Version, place.Region, x, yn, zoom)},
		{"C3M tile h0", fmt.Sprintf("%s?style=15&v=%d&region=%d&x=%d&y=%d&z=%d&h=0", c3mPfx, place.Version, place.Region, x, yn, zoom)},
	}
	for _, pr := range probes {
		st, ct, n := getStatus(sign(pr.url))
		fmt.Printf("  %-18s -> HTTP %-3d  %-26s %d bytes\n", pr.label, st, ct, n)
	}
}

func getStatus(u string) (int, string, int) {
	res, err := http.Get(u)
	if err != nil {
		return -1, err.Error(), 0
	}
	defer res.Body.Close()
	buf := make([]byte, 4096)
	total := 0
	for {
		k, e := res.Body.Read(buf)
		total += k
		if e != nil {
			break
		}
	}
	return res.StatusCode, res.Header.Get("content-type"), total
}

func nearest(am fly.AltitudeManifest, lat, lon float64) fly.Trigger {
	bd, best := math.Inf(1), fly.Trigger{}
	for _, v := range am.Triggers {
		d := math.Hypot(lat-v.Lat, lon-v.Lon)
		if d <= v.Radius && d < bd {
			bd, best = d, v
		}
	}
	return best
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
