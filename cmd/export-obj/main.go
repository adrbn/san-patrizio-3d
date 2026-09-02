package main

import (
	"errors"
	"fmt"
	"io/ioutil"
	"log"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/retroplasma/flyover-reverse-engineering/pkg/fly"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/fly/c3m"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/fly/c3mm"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/fly/exp"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mps"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mps/config"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/mth"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/oth"
	"github.com/retroplasma/flyover-reverse-engineering/pkg/web"
)

var l = log.New(os.Stderr, "", 0)

var errEmptyTile = errors.New("empty tile (no data after retries)")

func printUsage(msg string) {
	if msg != "" {
		l.Println("Error:", msg)
	}
	l.Println("Usage", os.Args[0], "[lat] [lon] [zoom] [tryXY] [tryH] [[--parallel]]")
	l.Println()
	l.Println("  Name    Description       Example")
	l.Println("  --------------------------------------")
	ex := []string{"34.007603", "-118.499741", "20", "3", "40"}
	l.Println("  lat     Latitude         ", ex[0])
	l.Println("  lon     Longitude        ", ex[1])
	l.Println("  zoom    Zoom (~ 13-20)   ", ex[2])
	l.Println("  tryXY   Area scan        ", ex[3])
	l.Println("  tryH    Altitude scan    ", ex[4])
	l.Println("Example:", os.Args[0], ex[0], ex[1], ex[2], ex[3], ex[4])
	os.Exit(1)
}

func main() {

	var err error
	aReq := make([]string, 0)
	aOpt := make([]string, 0)
	for _, a := range os.Args[1:] {
		if !strings.HasPrefix(a, "--") {
			aReq = append(aReq, a)
		} else {
			aOpt = append(aOpt, a)
		}
	}
	if len(os.Args) == 1 {
		printUsage("")
	}
	if len(aReq) != 5 {
		printUsage("Invalid argument number")
	}
	lat, err := strconv.ParseFloat(aReq[0], 64)
	if err != nil {
		printUsage("Invalid lat")
	}
	lon, err := strconv.ParseFloat(aReq[1], 64)
	if err != nil {
		printUsage("Invalid lon")
	}
	zoom, err := strconv.ParseInt(aReq[2], 10, 32)
	if err != nil {
		printUsage("Invalid zoom")
	}
	tryXY, err := strconv.ParseInt(aReq[3], 10, 32)
	if err != nil {
		printUsage("Invalid tryXY")
	}
	tryH, err := strconv.ParseInt(aReq[4], 10, 32)
	if err != nil {
		printUsage("Invalid tryH")
	}
	parallel := false
	for _, a := range aOpt {
		switch a {
		case "--parallel":
			parallel = true
		default:
			printUsage("Unknown param: " + a)
		}
	}

	cache := mps.Cache{Enabled: true, Directory: "./cache"}
	err = cache.Init()
	oth.CheckPanic(err)
	config, err := config.FromJSONFile("./config.json")
	oth.CheckPanic(err)
	if !config.IsValid() {
		fmt.Fprintln(os.Stderr, "please set values in config.json")
		os.Exit(1)
	}
	ctx, err := getContext(cache, config)
	oth.CheckPanic(err)

	z := int(zoom)
	x, y := mth.LatLonToTileTMS(z, lat, lon)

	p, err := ctx.findPlace(lat, lon)
	oth.CheckPanic(err)
	l.Println(p.Name, p.Radius, p.Lat, p.Lon)

	err = os.MkdirAll(fmt.Sprintf("./cache/c3mm/%d_%d", p.Region, p.Version), 0755)
	oth.CheckPanic(err)

	exportDir := fmt.Sprintf("./downloaded_files/obj/%f-%f-%d-%d-%d", lat, lon, zoom, tryXY, tryH)
	err = os.MkdirAll(exportDir, 0755)
	oth.CheckPanic(err)

	xp := 0
	export, err := exp.New(exportDir, "exp_")
	oth.CheckPanic(err)
	defer func() {
		oth.CheckPanic(export.Close())
	}()

	c3m.DisableLogs()

	// semaphore settings
	dln := 1
	if parallel {
		dln = 16
	}
	sem := make(chan int, dln)
	var wg sync.WaitGroup

	// exporter for decoded tiles
	ex, exDone := make(chan c3m.C3M, dln), make(chan int)
	go func() {
		for tile := range ex {
			oth.CheckPanic(export.Next(tile, fmt.Sprintf("%d", xp)))
			xp++
		}
		exDone <- 1
	}()

	// loop over area and altitude.
	//
	// Apple retired the C3MM_1 (style 14) octree that checkTile used to consult,
	// so it now 404s everywhere. Instead we probe the C3M tiles (style 15)
	// directly and skip the ones that don't exist (404 or jpeg placeholder).
	for dx := -tryXY; dx <= tryXY; dx++ {
		for dy := -tryXY; dy <= tryXY; dy++ {
			dx, dy := dx, dy
			sem <- 1
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer func() { <-sem }()
				xn := x + int(dx)
				yn := y + int(dy)
				// Heights are contiguous from 0. Walk up until tiles run out:
				// tolerate initial gaps, stop once we've seen tiles and then miss.
				seen := false
				for h := 0; h < int(tryH); h++ {
					tile, err := ctx.getTile(p, z, yn, xn, h)
					if err != nil {
						if isMissing(err) {
							if seen {
								break // heights exhausted for this column
							}
							continue // genuine gap, keep scanning up
						}
						// unexpected (e.g. parse error on odd content) — skip, don't abort
						l.Println("skip", dx, dy, "h =", h, ":", err)
						continue
					}
					seen = true
					l.Println("Exporting", dx, dy, "h =", h)
					ex <- tile
				}
			}()
		}
	}
	wg.Wait() // wait for all tile loads to finish
	close(ex) // no more tiles sent to exporter
	<-exDone  // wait till all tiles are exported
	l.Println(xp, "exported")

	// Apple ships textures as HEIC now; the .mtl references .jpg. Transcode any
	// HEIC the exporter wrote so the OBJ's map_Kd files exist and open anywhere.
	if n := transcodeHEIC(exportDir); n > 0 {
		l.Printf("transcoded %d HEIC texture(s) to JPEG", n)
	}
}

// transcodeHEIC converts every *.heic in dir to a sibling *.jpg and removes the
// HEIC. Uses macOS `sips`, falling back to `heif-convert` or ImageMagick.
func transcodeHEIC(dir string) int {
	heics, _ := filepath.Glob(filepath.Join(dir, "*.heic"))
	count := 0
	for _, hc := range heics {
		jpg := strings.TrimSuffix(hc, ".heic") + ".jpg"
		if convertOne(hc, jpg) {
			os.Remove(hc)
			count++
		} else {
			l.Println("warning: could not transcode", hc)
		}
	}
	return count
}

func convertOne(src, dst string) bool {
	try := [][]string{
		{"sips", "-s", "format", "jpeg", src, "--out", dst},
		{"heif-convert", "-q", "92", src, dst},
		{"magick", src, dst},
	}
	for _, c := range try {
		if _, err := exec.LookPath(c[0]); err != nil {
			continue
		}
		if err := exec.Command(c[0], c[1:]...).Run(); err == nil {
			if fi, e := os.Stat(dst); e == nil && fi.Size() > 0 {
				return true
			}
		}
	}
	return false
}

func (ctx *context) checkTile(p fly.Trigger, z, y, x, h int) (bool, error) {

	tile := c3mm.Tile{Z: z, Y: y, X: x, H: h}

	c3mm0, err := ctx.getC3mm(p, 0)
	if err != nil {
		return false, err
	}

	smallestZ := c3mm0.RootIndex.SmallestZ

	if tile.Z < smallestZ {
		return false, errors.New("z too small")
	}

	// list of tiles from requested to lowest level of detail
	list := make([]c3mm.Tile, 0)
	for t := tile; t.Z >= smallestZ; t = t.ZoomedOut() {
		list = append(list, t)
	}

	// find octree root
	root, listIdx := c3mm.Root{}, len(list)-1
	for ; listIdx >= 0; listIdx-- {
		t := list[listIdx]
		n := len(c3mm0.RootIndex.Entries)
		idx := sort.Search(n, func(i int) bool {
			root := c3mm0.RootIndex.Entries[i]
			return t.Less(root.Tile) || t == root.Tile
		})
		if idx == n {
			continue
		}
		root = c3mm0.RootIndex.Entries[idx]
		if t != root.Tile {
			continue
		}
		break
	}
	if listIdx < 0 {
		return false, nil
	}

	// readOctant reads an octant from c3mm files and moves the offset
	readOctant := func(octantOffset *int) (c3mm.Octant, error) {
		partNum := c3mm0.FileIndex.GetPartNumber(*octantOffset)
		c3mm1, err := ctx.getC3mm(p, partNum)
		if err != nil {
			return c3mm.Octant{}, err
		}
		return c3mm1.GetOctant(octantOffset, c3mm0.FileIndex.Entries[partNum]), nil
	}

	rootOffset := root.Offset
	octant, err := readOctant(&rootOffset)
	if err != nil {
		return false, err
	}

	if list[listIdx] == tile {
		return true, nil
	}
	if listIdx == 0 {
		return false, nil
	}

	// traverse octree
	for ; octant.Next > 0; listIdx-- {
		zoomedInActual := list[listIdx-1]
		zoomedInCandidates := list[listIdx].ZoomedInCandidates()
		bits := octant.Bits
		octantOffset := octant.Next
		matched := false
		for o := 0; o < 8; o++ {
			if (bits>>(o*2))&1 != 1 {
				continue
			}
			octant, err = readOctant(&octantOffset)
			if err != nil {
				return false, err
			}
			if zoomedInCandidates(o) == zoomedInActual {
				matched = true
				break
			}
		}
		if !matched {
			return false, nil
		}
		if tile == zoomedInActual {
			return true, nil
		}
	}
	return false, nil
}

// isMissing reports whether an error from getTile means "no tile here"
// (HTTP 404, or the jpeg placeholder Apple returns when there's no C3M),
// as opposed to a real failure.
func isMissing(err error) bool {
	if err == nil {
		return false
	}
	s := err.Error()
	return err == errEmptyTile ||
		strings.Contains(s, "http status 404") ||
		strings.Contains(s, "received jpeg") ||
		strings.Contains(s, "Invalid C3M header")
}

func (ctx *context) getTile(p fly.Trigger, z, y, x, h int) (c3m.C3M, error) {
	yn := mth.TileCountPerAxis(z) - 1 - y // invert y
	url := fmt.Sprintf("%s?style=%d&v=%d&region=%d&x=%d&y=%d&z=%d&h=%d",
		ctx.URLPrefixC3m, mps.ResourceManifest_StyleConfig_C3M, p.Version, p.Region, x, yn, z, h)

	// Apple primes Flyover tiles on demand: the first request(s) can return an
	// empty 200 while the tile is generated server-side, then it serves data.
	// Retry empty responses with backoff before deciding the tile is absent.
	var data []byte
	var err error
	for attempt := 0; attempt < 6; attempt++ {
		data, err = ctx.get(url)
		if err != nil {
			return c3m.C3M{}, err // 404 / jpeg / network — real signal
		}
		if len(data) > 0 {
			break
		}
		time.Sleep(time.Duration(700+attempt*500) * time.Millisecond)
	}
	if os.Getenv("DBG") != "" {
		pfx := data
		if len(pfx) > 16 {
			pfx = pfx[:16]
		}
		l.Printf("GET h=%d -> %d bytes first=%q", h, len(data), string(pfx))
		if dp := os.Getenv("DUMP"); dp != "" && len(data) > 0 {
			ioutil.WriteFile(dp, data, 0644)
			l.Printf("dumped %d bytes -> %s", len(data), dp)
		}
	}
	if len(data) == 0 {
		return c3m.C3M{}, errEmptyTile
	}
	return c3m.Parse(data)
}

func (ctx *context) getC3mm(p fly.Trigger, part int) (c3mm.C3MM, error) {
	if ctx.C3mms == nil || ctx.C3mms[part] == nil {
		data, err := ctx._getC3mm(p, part)
		if err != nil {
			return c3mm.C3MM{}, err
		}
		if part == 0 {
			ctx.C3mms = make([]*c3mm.C3MM, len(data.FileIndex.Entries))
		}
		ctx.C3mms[part] = &data
		return data, nil
	}
	return *ctx.C3mms[part], nil
}

func (ctx *context) _getC3mm(p fly.Trigger, part int) (c3mm.C3MM, error) {
	fn := fmt.Sprintf("./cache/c3mm/%d_%d/%d", p.Region, p.Version, part)
	file, err := ioutil.ReadFile(fn)
	if err != nil && !os.IsNotExist(err) {
		return c3mm.C3MM{}, err
	}
	if err == nil {
		return c3mm.Parse(file, part)
	}
	data, err := ctx.get(fmt.Sprintf("%s?style=%d&v=%d&part=%d&region=%d",
		ctx.URLPrefixC3mm, mps.ResourceManifest_StyleConfig_C3MM_1, p.Version, part, p.Region))
	if err != nil {
		return c3mm.C3MM{}, err
	}
	if ioutil.WriteFile(fn+".tmp", data, 0655) != nil {
		return c3mm.C3MM{}, err
	}
	if os.Rename(fn+".tmp", fn) != nil {
		return c3mm.C3MM{}, err
	}
	return c3mm.Parse(data, part)
}

func (ctx context) findPlace(lat, lon float64) (fly.Trigger, error) {
	// radius non spherical yet
	minDist, minPlace := math.Inf(1), fly.Trigger{}

	for _, v := range ctx.AltitudeManifest.Triggers {
		dist := math.Sqrt(math.Pow(lat-v.Lat, 2) + math.Pow(lon-v.Lon, 2))
		// radius can overlap. ignored for now
		if dist <= v.Radius && dist < minDist {
			minDist, minPlace = dist, v
		}
	}
	if minDist == math.Inf(1) {
		return fly.Trigger{}, errors.New("minPlace not found")
	}
	return minPlace, nil
}

func (ctx context) get(url string) ([]byte, error) {
	authURL, err := ctx.Context.AuthContext.AuthURL(url)
	if err != nil {
		return nil, err
	}
	return get(authURL)
}

func get(url string) (data []byte, err error) {
	jpgErr := errors.New("received jpeg")
	data, err = web.GetWithCheck(url, func(res *http.Response) (err error) {
		// fail early if there's a jpeg, which is sometimes sent if there's no c3m(m)
		if res.Header.Get("content-type") == "image/jpeg" {
			err = jpgErr
		}
		return
	})
	return
}

type context struct {
	Context          mps.Context
	AltitudeManifest fly.AltitudeManifest
	URLPrefixC3mm    string
	URLPrefixC3m     string
	C3mms            []*c3mm.C3MM
}

func getContext(cache mps.Cache, config config.Config) (m context, err error) {
	ctx, err := mps.Init(cache, config)
	if err != nil {
		return
	}
	am, err := fly.GetAltitudeManifest(cache, ctx.ResourceManifest)
	if err != nil {
		return
	}

	c3mmURLPrefix, err := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3MM_1)
	if err != nil {
		return
	}
	c3mURLPrefix, err := ctx.ResourceManifest.URLPrefixFromStyleID(mps.ResourceManifest_StyleConfig_C3M)
	if err != nil {
		return
	}

	m = context{ctx, am, c3mmURLPrefix, c3mURLPrefix, nil}
	return
}
