/* -*- c -*- */

#version 420

layout(location = 0) out vec4 frag_color;
in vec2 tex_fragment;
uniform sampler2D tex;

uniform int NtilesX, NtilesY;

// shading_scale is 0.0 (disabled: legacy unshaded rendering) or 1.0
// (enabled). sun_dir is a unit vector in the same (east,north,height)
// frame as normal_fragment, pointing FROM the terrain TOWARDS the sun
uniform float shading_scale;
uniform vec3  sun_dir;
in vec3 normal_fragment;

// materials_scale is 0.0 (disabled: no material tint) or 1.0 (enabled).
// A first, purely procedural land-cover approximation -- no aerial
// imagery or land-cover data involved -- classifying each fragment by
// elevation (snow line) and slope steepness (bare rock), with forest
// below the tree line and alpine grass above it otherwise
uniform float materials_scale;
in float elevation_fragment;

// Real land-cover classes (see landcover.h), from pre-baked ESA WorldCover /
// IGN OCS GE / CORINE Land Cover tiles (build-landcover-tiles.py): one
// texture-array layer per loaded 1-degree tile (see landcover_tile_layer),
// north row first, (landcover_cells_per_deg+1)^2 cells per layer (see
// make_landcover_texture() in horizonator-lib.c). landcover_cells_per_deg
// is 0 if no tile was loaded. Looked up per fragment, at the fragment's
// interpolated DEM cell coordinates, so the land cover isn't limited to
// the mesh resolution
uniform usampler2DArray landcover_tex;
uniform int   landcover_cells_per_deg;
uniform ivec2 landcover_Ndems;
// Texture layer of each tile (tile_j*Ndems_x + tile_i), or -1 if that tile
// has no data. 36 = max_Ndems_ij^2 (dem.h)
uniform int   landcover_tile_layer[36];
// DEM cell coordinates of the mesh's (0,0) cell, counted from the SW
// corner of the origin tile; and the DEM resolution
uniform vec2  landcover_origin_cell;
uniform float landcover_dem_cells_per_deg;
in vec2 cell_ij_fragment;

// 0 at znear_color, 1 at zfar_color (see vertex.glsl)
in float atmo_t_fragment;

const float SNOW_LINE_M   = 2800.0; // above this: snow, any slope
const float TREE_LINE_M   = 1800.0; // below (and not snow/rock): forest

// Vegetation on a steep slope turns to bare rock progressively: fully its
// own color below SLOPE_ROCK_DEG_START, fully COLOR_ROCK above
// SLOPE_ROCK_DEG_END, smoothly blended in between (see rock_weight())
const float SLOPE_ROCK_DEG_START = 35.0;
const float SLOPE_ROCK_DEG_END   = 47.0;

// Subtle variation of color inside each land-cover class (see
// class_variation()): relative luminance amplitude per class
const float VARIATION_VEGETATION = 0.07;
const float VARIATION_ROCK       = 0.05;
const float VARIATION_SNOW       = 0.02;

// Snow in the shade is lit by the blue sky instead of the sun: its color
// tends towards this as the slope turns away from the sun (multiplied by
// the slope shading like everything else)
const vec3 COLOR_SNOW_SHADOW = vec3(0.80, 0.87, 1.00);

// For class_variation(): meters per degree of latitude, and the viewer's
// cos(latitude) (set for vertex.glsl too) for the east-west scale
const float M_PER_DEG = 111320.0;
uniform float cos_viewer_lat;

const vec3 COLOR_FOREST = vec3(0.35, 0.42, 0.30);
const vec3 COLOR_GRASS  = vec3(0.55, 0.58, 0.38);
const vec3 COLOR_ROCK   = vec3(0.50, 0.47, 0.43);
const vec3 COLOR_SNOW   = vec3(0.95, 0.96, 0.98);
const vec3 COLOR_WATER  = vec3(0.28, 0.38, 0.45);

// Finer nuances only IGN OCS GE (not WorldCover) can tell apart: cooler,
// darker green for conifers; warmer, lighter green for deciduous; alpine
// heath/scrub (also WorldCover's Shrubland) between grass and rock
const vec3 COLOR_FOREST_CONIFER   = vec3(0.28, 0.37, 0.27);
const vec3 COLOR_FOREST_DECIDUOUS = vec3(0.42, 0.48, 0.28);
const vec3 COLOR_SHRUB            = vec3(0.50, 0.52, 0.32);

// Must match horizonator_landcover_class_t in landcover.h
#define LANDCOVER_UNKNOWN            0.0
#define LANDCOVER_FOREST             1.0
#define LANDCOVER_GRASS              2.0
#define LANDCOVER_ROCK               3.0
#define LANDCOVER_SNOWICE            4.0
#define LANDCOVER_WATER              5.0
#define LANDCOVER_FOREST_DECIDUOUS   6.0
#define LANDCOVER_FOREST_CONIFER     7.0
#define LANDCOVER_SHRUB              8.0

// Used as the near (atmo_t==0) color when materials_scale==0: this is
// the plain-grayscale look (no material data), a dark neutral gray purely
// for visual weight/contrast -- not a claim about what's really there.
// When materials ARE on, the material's own true color is used as the
// near color instead (see main() below): a real land-cover color
// shouldn't ALSO be darkened by this legacy gray, or the two darkening
// effects compound (near-dark-gray times a dim material times slope
// shading was crushing near, shaded forest to near black)
const vec3 COLOR_NEAR_DEFAULT = vec3(0.30, 0.30, 0.30);

// The far (atmo_t==1) color, regardless of materials: a pale blue-gray
// haze, the way atmospheric scattering tints distant relief in a real
// photo. This one genuinely is distance-dependent physics (haze), unlike
// COLOR_NEAR_DEFAULT above, so it applies the same whether or not
// materials are on
const vec3 COLOR_FAR = vec3(0.80, 0.84, 0.92);

// How much of a vegetation color turns to bare rock on a slope whose normal
// has vertical component slope_nz (cos of the slope angle): 0 below
// SLOPE_ROCK_DEG_START, 1 above SLOPE_ROCK_DEG_END. Progressive rather than
// all-or-nothing: a hard threshold drew sharp green/gray boundaries
// following the contour of the slope angle rather than of the vegetation,
// and turned steep but grassy slopes entirely gray
float rock_weight(float slope_nz)
{
    return 1.0 - smoothstep(cos(radians(SLOPE_ROCK_DEG_END)),
                            cos(radians(SLOPE_ROCK_DEG_START)),
                            slope_nz);
}

// Snow, bluish where it turns away from the sun (lit by the sky instead).
// ndotl is the cosine between the surface normal and the sun direction;
// with shading off, no slope faces away from the sun, so plain white
vec3 snow_color(float ndotl)
{
    return mix(COLOR_SNOW, COLOR_SNOW_SHADOW, (1.0 - ndotl) * shading_scale);
}

// Hash-based value noise in [-1,1], smooth, unit feature size
float hash12(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float value_noise(vec2 p)
{
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f*f*(3.0 - 2.0*f);
    return mix(mix(hash12(i),               hash12(i + vec2(1.0, 0.0)), u.x),
               mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x),
               u.y) * 2.0 - 1.0;
}

// One octave of noise at feature size size_m, faded out where it would be
// smaller than a pixel (it would only shimmer there, not read as texture)
float noise_octave(vec2 ground_m, float size_m)
{
    vec2  p     = ground_m / size_m;
    float fade  = 1.0 - smoothstep(0.3, 0.8, max(fwidth(p).x, fwidth(p).y));
    return value_noise(p) * fade;
}

// Subtle, irregular variation for color c inside one land-cover class, so
// a class isn't a flat, uniform patch: luminance by +-amplitude, plus a
// slight warm/cool drift. A function of the position ON THE GROUND, so it's
// stable from one render (or panorama tile) to the next
vec3 class_variation(vec3 c, float amplitude, vec2 cell_ij)
{
    vec2 deg      = (cell_ij + landcover_origin_cell) / landcover_dem_cells_per_deg;
    vec2 ground_m = deg * vec2(M_PER_DEG * cos_viewer_lat, M_PER_DEG);

    float lum  = 0.6*noise_octave(ground_m, 600.0) + 0.4*noise_octave(ground_m, 150.0);
    float tint = noise_octave(ground_m + vec2(5000.0), 900.0);

    return c * (1.0 + amplitude*lum) +
           vec3(0.5, 0.2, -0.5) * (amplitude*0.25*tint);
}

// Purely procedural fallback, used wherever no real land-cover data was
// baked in for this point (landcover_class_at() == LANDCOVER_UNKNOWN):
// no aerial imagery or land-cover data involved, just elevation (snow
// line) and slope steepness (bare rock), with forest below the tree line
// and alpine grass above it otherwise
//
// Same steep-slope rock and snow shading rules as material_color() below
vec3 material_color_procedural(float elevation, float slope_nz, float ndotl)
{
    if(elevation > SNOW_LINE_M)
        return snow_color(ndotl);
    vec3 vegetation = elevation > TREE_LINE_M ? COLOR_GRASS : COLOR_FOREST;
    return mix(vegetation, COLOR_ROCK, rock_weight(slope_nz));
}

// The LANDCOVER_* class at DEM cell coordinates cell_ij (fractional), or
// LANDCOVER_UNKNOWN if there's no data there
float landcover_class_at(vec2 cell_ij)
{
    if(landcover_cells_per_deg == 0)
        return LANDCOVER_UNKNOWN;

    // Degrees from the SW corner of the origin tile
    vec2  deg  = (cell_ij + landcover_origin_cell) / landcover_dem_cells_per_deg;
    // A point exactly on the far edge of the last tile belongs to that
    // tile (adjacent tiles overlap by one cell, so either one would do
    // everywhere else)
    ivec2 tile = clamp(ivec2(floor(deg)), ivec2(0), landcover_Ndems - 1);
    vec2  frac = deg - vec2(tile);
    if(any(lessThan(frac, vec2(0.0))) || any(greaterThan(frac, vec2(1.0))))
        return LANDCOVER_UNKNOWN;

    // Class codes can't be interpolated, but nearest-neighbor lookups give
    // square, grid-aligned class boundaries, very visible at the grazing
    // angles of a panorama. So: look at the 4 cells around this point and
    // keep the class with the highest total bilinear weight. Same cost in
    // memory, but the boundaries between classes come out as smooth curves
    // through the cells instead of staircases along their edges
    int   n    = landcover_cells_per_deg;
    vec2  p    = frac * float(n);
    ivec2 p0   = min(ivec2(floor(p)), ivec2(n-1));
    vec2  f    = p - vec2(p0);
    int   layer = landcover_tile_layer[tile.y*landcover_Ndems.x + tile.x];
    if(layer < 0)
        return LANDCOVER_UNKNOWN;

    // Rows are stored north row first
    uint c[4];
    c[0] = texelFetch(landcover_tex, ivec3(p0.x,   n - p0.y,     layer), 0).r;
    c[1] = texelFetch(landcover_tex, ivec3(p0.x+1, n - p0.y,     layer), 0).r;
    c[2] = texelFetch(landcover_tex, ivec3(p0.x,   n - p0.y - 1, layer), 0).r;
    c[3] = texelFetch(landcover_tex, ivec3(p0.x+1, n - p0.y - 1, layer), 0).r;
    float w[4];
    w[0] = (1.0-f.x)*(1.0-f.y);
    w[1] =      f.x *(1.0-f.y);
    w[2] = (1.0-f.x)*     f.y;
    w[3] =      f.x *     f.y;

    uint  best        = c[0];
    float best_weight = -1.0;
    for(int k=0; k<4; k++)
    {
        float weight = 0.0;
        for(int l=0; l<4; l++)
            if(c[l] == c[k])
                weight += w[l];
        if(weight > best_weight)
        {
            best        = c[k];
            best_weight = weight;
        }
    }
    return float(best);
}

// landcover_class is a float holding one of the LANDCOVER_* integer codes
// above (from landcover_class_at(), so an exact integral value, not
// needing to be rounded). LANDCOVER_UNKNOWN falls
// back to the procedural elevation/slope classification: real data is
// preferred wherever build-landcover-tiles.py has prepared it, but a point
// outside that coverage should still get an approximate material, not the
// flat legacy gray
//
// A real, planimetric land-cover source (OCS GE/WorldCover, both derived
// from an overhead view) can't be trusted on a near-vertical slope: the
// DEM itself can only represent a cliff as a steep ramp spanning several
// cells, never a true vertical face, so the sample taken there can land
// on the horizontal footprint of neighboring vegetated terrain instead of
// the cliff's actual rock. This shows up as green cliffs, and is far more
// visible in a grazing panorama view than it would be looking straight
// down at a map. So: vegetation turns to rock on steep slopes (progressively,
// see rock_weight()), same as in the procedural fallback above -- but only
// the vegetation classes: LANDCOVER_ROCK/SNOWICE/WATER stay as classified,
// since a steep slope is unremarkable for bare rock and can be entirely
// legitimate for a couloir/icefall or a cliff behind a lake
//
// Every class then gets a subtle variation (class_variation()), so it
// doesn't read as one flat patch of color
vec3 material_color(float landcover_class, float elevation, float slope_nz,
                    float ndotl, vec2 cell_ij)
{
    vec3  vegetation;
    if     (landcover_class == LANDCOVER_FOREST)           vegetation = COLOR_FOREST;
    else if(landcover_class == LANDCOVER_GRASS)            vegetation = COLOR_GRASS;
    else if(landcover_class == LANDCOVER_FOREST_DECIDUOUS) vegetation = COLOR_FOREST_DECIDUOUS;
    else if(landcover_class == LANDCOVER_FOREST_CONIFER)   vegetation = COLOR_FOREST_CONIFER;
    else if(landcover_class == LANDCOVER_SHRUB)            vegetation = COLOR_SHRUB;
    else if(landcover_class == LANDCOVER_ROCK)
        return class_variation(COLOR_ROCK, VARIATION_ROCK, cell_ij);
    else if(landcover_class == LANDCOVER_SNOWICE)
        return class_variation(snow_color(ndotl), VARIATION_SNOW, cell_ij);
    else if(landcover_class == LANDCOVER_WATER)
        return COLOR_WATER;
    else
        return class_variation(material_color_procedural(elevation, slope_nz, ndotl),
                               VARIATION_VEGETATION, cell_ij);

    float rock_w = rock_weight(slope_nz);
    return class_variation(mix(vegetation, COLOR_ROCK, rock_w),
                           mix(VARIATION_VEGETATION, VARIATION_ROCK, rock_w),
                           cell_ij);
}

void main(void)
{
    // normal_fragment is linearly interpolated (by the rasterizer) from
    // the 3 per-vertex normals of the enclosing triangle, so it isn't
    // unit length in general; renormalize before using it
    vec3 n = normalize(normal_fragment);

    float ndotl = max(dot(n, sun_dir), 0.0);
    // Ambient floor of 0.5: a slope facing away from the sun is dimmer,
    // not black
    float light = mix(0.5, 1.0, ndotl);
    // shading_scale==0 must reproduce the old, unshaded look exactly
    float light_scaled = mix(1.0, light, shading_scale);

    // materials_scale==0 must reproduce the old, untinted look exactly:
    // mix(COLOR_NEAR_DEFAULT, material_color(...), 0.0) == COLOR_NEAR_DEFAULT
    vec3 near_color = COLOR_NEAR_DEFAULT;
    if(materials_scale > 0.0)
        near_color = mix(COLOR_NEAR_DEFAULT,
                         material_color(landcover_class_at(cell_ij_fragment),
                                        elevation_fragment, n.z,
                                        ndotl, cell_ij_fragment),
                         materials_scale);

    // Atmospheric haze: blend towards the far color with distance. This
    // is the ONLY distance-dependent darkening/tinting left (on top of
    // whichever near_color was picked above) -- unlike before, materials
    // no longer also get multiplied by a separate near/far gray gradient
    vec3 rgb = mix(near_color, COLOR_FAR, atmo_t_fragment);

    vec3 rgb_shaded = rgb * light_scaled;

    if(NtilesX == 0)
        frag_color = vec4(rgb_shaded, 1.0);
    else
    {
        vec4 texcolor     = texture( tex, tex_fragment.xy);
        vec4 shadingcolor = vec4(rgb_shaded, 0.0);
        frag_color = 0.7*texcolor + 0.3*shadingcolor;
    }
}
