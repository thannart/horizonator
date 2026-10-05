#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "dem.h"

// Land-cover classification, from pre-baked tiles built offline by
// build-landcover-tiles.py (ESA WorldCover base layer, IGN OCS GE overlay in
// France, CORINE Land Cover glacier overlay everywhere -- see that script
// and README.org for details).
//
// This mirrors dem.h/dem.c on purpose: same 1-degree tile grid, same
// mmap-on-demand loading, same missing-tile tolerance. The tile layout
// (origin tile, number of tiles) is taken directly from an
// already-initialized horizonator_dem_context_t rather than recomputed, so
// the two grids can never disagree with each other. The resolution INSIDE
// each tile is independent of the DEM's, however: a '.landcover' file is a
// square (N+1)x(N+1) byte grid, N cells per degree, and N is inferred from
// the file size. The tiles are uploaded to the GPU as a texture and
// sampled per fragment (see fragment.glsl), so land cover baked finer than
// the DEM shows up finer than the mesh, instead of one class per mesh
// vertex
//
// Values are a stored byte format (baked into '.landcover' files on disk,
// see build-landcover-tiles.py), so existing values must never be
// renumbered or repurposed -- only append new ones after the last one, so
// tiles baked by an older version of the script keep meaning what they
// always meant
typedef enum
{
    LANDCOVER_UNKNOWN = 0, // no data here: caller should fall back to the
                           // procedural elevation/slope classification
    LANDCOVER_FOREST  = 1, // forest, subtype unknown -- WorldCover (which
                           // can't distinguish deciduous/conifer) and OCS
                           // GE's "mixed stand" class both land here
    LANDCOVER_GRASS   = 2,
    LANDCOVER_ROCK    = 3,
    LANDCOVER_SNOWICE = 4,
    LANDCOVER_WATER   = 5,

    // OCS GE-only distinctions (WorldCover has no equivalent class, so
    // these never come from that source): a real land-cover source with
    // per-country resolution better than WorldCover's should be free to
    // add more nuance than the 6 classes above, without disturbing them
    LANDCOVER_FOREST_DECIDUOUS = 6,
    LANDCOVER_FOREST_CONIFER   = 7,
    LANDCOVER_SHRUB            = 8, // alpine heath/scrub -- WorldCover's
                                    // Shrubland also maps here
} horizonator_landcover_class_t;

typedef struct
{
    unsigned char* tiles     [max_Ndems_ij][max_Ndems_ij];
    size_t         mmap_sizes[max_Ndems_ij][max_Ndems_ij];
    int            mmap_fd   [max_Ndems_ij][max_Ndems_ij];

    // Cells per degree of each tile, inferred from its file size; 0 if
    // that tile is missing. Tiles baked at different resolutions can be
    // mixed
    int            tile_cells_per_deg[max_Ndems_ij][max_Ndems_ij];

    // Borrowed from the horizonator_dem_context_t this was init'd from: the
    // two grids share this tile layout exactly, so it isn't recomputed here
    int origin_dem_lon_lat[2];
    int Ndems_ij          [2];

    // The highest tile_cells_per_deg[][] of all the loaded tiles, or 0 if no
    // tile was loaded at all. The GPU texture uses this resolution for
    // every tile (see horizonator_landcover_tile_resampled())
    int max_cells_per_deg;
} horizonator_landcover_context_t;

// dem_ctx must already be initialized (horizonator_dem_init()). Its tile
// layout is reused as-is. Missing or malformed '.landcover' tile files are
// tolerated (same as dem.c tolerates a missing '.hgt'): that tile reads
// back as LANDCOVER_UNKNOWN
bool horizonator_landcover_init(// output
                                horizonator_landcover_context_t* ctx,

                                // input
                                const horizonator_dem_context_t* dem_ctx,
                                const char* datadir);

void horizonator_landcover_deinit( horizonator_landcover_context_t* ctx );

// Unmaps and closes one tile (same indexing as ctx->tiles); it then reads
// as missing. Lets a caller that copies the tiles elsewhere (the GPU
// texture) drop each one as soon as it's copied, instead of keeping them
// all resident until horizonator_landcover_deinit(). Harmless on a tile
// that's already released or was never loaded
void horizonator_landcover_release_tile( horizonator_landcover_context_t* ctx,
                                         int i, int j );

// Writes tile (i,j) (same indexing as ctx->tiles: relative to the origin
// tile) into out[], resampled (nearest neighbor) to cells_per_deg:
// (cells_per_deg+1)^2 bytes, in the same row order as the files (north row
// first). A missing tile is written as all LANDCOVER_UNKNOWN
void horizonator_landcover_tile_resampled(// output
                                          uint8_t* out,

                                          // input
                                          const horizonator_landcover_context_t* ctx,
                                          int i, int j,
                                          int cells_per_deg);
