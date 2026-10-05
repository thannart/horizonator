#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <math.h>
#include <sys/fcntl.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <string.h>
#include <unistd.h>

#include "landcover.h"
#include "util.h"

static
bool landcover_filename(// output
                        char* path, int bufsize,

                        // input
                        int demfileN, int demfileE,
                        const char* datadir )
{
    char ns;
    char we;

    if     ( demfileN >= 0 && demfileE >= 0 )
    {
        ns = 'N'; we = 'E';
    }
    else if( demfileN >= 0 && demfileE <  0 )
    {
        ns = 'N'; we = 'W';
        demfileE *= -1;
    }
    else if( demfileN  < 0 && demfileE >= 0 )
    {
        ns = 'S'; we = 'E';
        demfileN *= -1;
    }
    else
    {
        ns = 'S'; we = 'W';
        demfileN *= -1;
        demfileE *= -1;
    }

    if(datadir[0] == '~' && datadir[1] == '/' )
    {
        const char* home = getenv("HOME");
        if(home == NULL)
        {
            MSG("User asked for ~, but the 'HOME' env var isn't defined");
            return false;
        }
        if( snprintf(path, bufsize, "%s/%s/%c%.2d%c%.3d.landcover",
                     home,
                     &datadir[2],
                     ns, demfileN, we, demfileE) >= bufsize )
            return false;
    }
    else
    {
        if( snprintf(path, bufsize, "%s/%c%.2d%c%.3d.landcover",
                     datadir,
                     ns, demfileN, we, demfileE) >= bufsize )
            return false;
    }
    return true;
}

bool horizonator_landcover_init(// output
                                horizonator_landcover_context_t* ctx,

                                // input
                                const horizonator_dem_context_t* dem_ctx,
                                const char* datadir)
{
    *ctx = (horizonator_landcover_context_t){};

    // Borrow the DEM tile layout outright: the two tile sets cover the
    // exact same 1-degree tiles, so recomputing this here could only ever
    // introduce a mismatch, never fix one
    memcpy(ctx->origin_dem_lon_lat, dem_ctx->origin_dem_lon_lat, sizeof(ctx->origin_dem_lon_lat));
    memcpy(ctx->Ndems_ij,           dem_ctx->Ndems_ij,           sizeof(ctx->Ndems_ij));

    for( int j = 0; j < ctx->Ndems_ij[1]; j++ )
        for( int i = 0; i < ctx->Ndems_ij[0]; i++ )
        {
            char filename[1024];
            if( !landcover_filename( filename, sizeof(filename),
                                     j + ctx->origin_dem_lon_lat[1],
                                     i + ctx->origin_dem_lon_lat[0],
                                     datadir) )
            {
                horizonator_landcover_deinit(ctx);
                MSG("Couldn't construct landcover filename" );
                return false;
            }

            struct stat sb;
            ctx->mmap_fd[i][j] = open( filename, O_RDONLY );
            if( ctx->mmap_fd[i][j] <= 0 )
            {
                // Not fatal: no real land-cover data here just means every
                // sample in this tile reads back as LANDCOVER_UNKNOWN, and
                // the fragment shader falls back to the procedural
                // elevation/slope classification for those points. Missing
                // tiles are the expected state until build-landcover-tiles.py
                // has been run for this area, so this is quiet (no warning)
                ctx->tiles     [i][j] = NULL;
                ctx->mmap_sizes[i][j] = 0;
                ctx->mmap_fd   [i][j] = 0;
                continue;
            }

            int res = fstat(ctx->mmap_fd[i][j], &sb);
            assert( res == 0 );

            // The tile's resolution comes from its size alone: a square
            // (N+1)x(N+1) grid (adjacent tiles overlap by one cell, like
            // the .hgt files), any N. It doesn't have to match the DEM's
            // resolution: tiles are resampled into a common texture
            // resolution anyway (horizonator_landcover_tile_resampled()). A
            // file that isn't such a square is treated the same as a
            // missing one -- a warning, not a hard failure: aborting the
            // whole render over one bad tile would be a much worse outcome
            // than just falling back to the procedural classification for
            // that tile's area
            int width = (int)round(sqrt((double)sb.st_size));
            if(sb.st_size == 0 || width < 2 || (off_t)width*width != sb.st_size)
            {
                if(sb.st_size != 0)
                    MSG("The landcover file '%s' has unexpected size (%zu; expected a square (N+1)x(N+1) grid) -- ignoring it",
                        filename, (size_t)sb.st_size);
                close(ctx->mmap_fd[i][j]);

                ctx->tiles     [i][j] = NULL;
                ctx->mmap_sizes[i][j] = 0;
                ctx->mmap_fd   [i][j] = 0;
                continue;
            }

            ctx->tiles     [i][j] = mmap(NULL, sb.st_size, PROT_READ, MAP_PRIVATE, ctx->mmap_fd[i][j], 0);
            ctx->mmap_sizes[i][j] = sb.st_size;

            if( ctx->tiles[i][j] == MAP_FAILED )
            {
                horizonator_landcover_deinit(ctx);
                MSG("Couldn't mmap the landcover file '%s'", filename );
                return false;
            }

            ctx->tile_cells_per_deg[i][j] = width - 1;
            if(ctx->max_cells_per_deg < width - 1)
                ctx->max_cells_per_deg = width - 1;
        }

    return true;
}

void horizonator_landcover_release_tile( horizonator_landcover_context_t* ctx,
                                         int i, int j )
{
    if( ctx->tiles[i][j] != NULL && ctx->tiles[i][j] != MAP_FAILED )
    {
        munmap( ctx->tiles[i][j], ctx->mmap_sizes[i][j] );
        ctx->tiles[i][j] = NULL;
    }
    if( ctx->mmap_fd[i][j] > 0 )
    {
        close( ctx->mmap_fd[i][j] );
        ctx->mmap_fd[i][j] = 0;
    }
}

void horizonator_landcover_deinit( horizonator_landcover_context_t* ctx )
{
    for( int i=0; i<max_Ndems_ij; i++)
        for( int j=0; j<max_Ndems_ij; j++)
            horizonator_landcover_release_tile(ctx, i, j);
}

void horizonator_landcover_tile_resampled(// output
                                          uint8_t* out,

                                          // input
                                          const horizonator_landcover_context_t* ctx,
                                          int i, int j,
                                          int cells_per_deg)
{
    const int width_out = cells_per_deg + 1;

    const unsigned char* tile = ctx->tiles[i][j];
    if(tile == NULL)
    {
        memset(out, LANDCOVER_UNKNOWN, (size_t)width_out*width_out);
        return;
    }

    const int cells_per_deg_in = ctx->tile_cells_per_deg[i][j];
    const int width_in         = cells_per_deg_in + 1;

    if(cells_per_deg_in == cells_per_deg)
    {
        memcpy(out, tile, (size_t)width_out*width_out);
        return;
    }

    // Nearest neighbor: a class code can't be interpolated. Both grids
    // span the same degree, edge to edge, so cell k of the output sits at
    // k*cells_per_deg_in/cells_per_deg in the input
    for(int r=0; r<width_out; r++)
    {
        int r_in = (int)(((int64_t)r*cells_per_deg_in*2 + cells_per_deg) / (2*cells_per_deg));
        for(int c=0; c<width_out; c++)
        {
            int c_in = (int)(((int64_t)c*cells_per_deg_in*2 + cells_per_deg) / (2*cells_per_deg));
            out[(size_t)r*width_out + c] = tile[(size_t)r_in*width_in + c_in];
        }
    }
}
