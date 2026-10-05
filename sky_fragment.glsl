/* -*- c -*- */

#version 420

layout(location = 0) out vec4 frag_color;
in vec2 ndc;

// Same az_deg0/az_deg1/aspect convention as vertex.glsl (see the formula
// reconstructed in horizonator_render_offscreen()'s range-image code):
//   az_ndc = (az - az_center) * 2 / (az1 - az0)
//   el_ndc = atan(z, length(en)) * aspect * 2 / (az1 - az0)
// This shader inverts both to recover (azimuth, elevation) for the
// direction each sky pixel represents, then colors it procedurally --
// no geometry, just a gradient plus a soft glow around the sun
uniform float az_deg0, az_deg1;
uniform float aspect;

// Unit vector pointing FROM the scene TOWARDS the sun, same (east,north,
// height) frame as horizonator_set_sun() gives the terrain shader
uniform vec3 sun_dir;

// COLOR_HORIZON matches fragment.glsl's COLOR_FAR exactly, so the sky
// meets the terrain's atmospheric haze with no visible seam at the
// horizon. COLOR_ZENITH is a plain mid-blue; real atmospheric scattering
// is bluest overhead and pales towards the horizon, which this mimics
// without needing an actual scattering model
const vec3 COLOR_HORIZON = vec3(0.80, 0.84, 0.92);
const vec3 COLOR_ZENITH  = vec3(0.45, 0.62, 0.85);

// Warm glow around the sun itself (visible only if the sun direction
// falls within the rendered azimuth/elevation window) and a gentle
// overall warm tint on the side of the sky facing the sun otherwise --
// the way the sky looks warmer near a low sun even outside its direct
// glow
const vec3 COLOR_SUNGLOW = vec3(1.00, 0.88, 0.70);

void main(void)
{
    float az_rad0 = radians(az_deg0);
    float az_rad1 = radians(az_deg1);
    float az_ndc_per_rad = 2.0 / (az_rad1 - az_rad0);

    float az = (az_rad0 + az_rad1) * 0.5 + ndc.x / az_ndc_per_rad * 0.5;
    float el = ndc.y / (aspect * az_ndc_per_rad);

    float cos_el = cos(el);
    vec3 dir = vec3(cos_el * sin(az),   // east
                    cos_el * cos(az),   // north
                    sin(el));           // up

    // Screen-space gradient (bottom of frame to top), not elevation-angle
    // based: at this renderer's usual very long range (tens to ~100+km),
    // the whole visible sky band is often only 1-2 true degrees of
    // elevation, so a gradient driven by the real angle barely moves at
    // all. pow(...,0.7) biases it towards COLOR_ZENITH even low in the
    // frame, so the sky reads as clearly blue rather than mostly pale
    // horizon haze
    float t = pow(clamp((ndc.y + 1.0) * 0.5, 0.0, 1.0), 0.7);
    vec3 color = mix(COLOR_HORIZON, COLOR_ZENITH, t);

    float sun_dot = dot(dir, sun_dir);
    // Tight, bright core for a visible sun/glow where it's actually in
    // frame, plus a much broader, faint warm wash so the sky still reads
    // as sunlit even when the sun itself is outside the rendered azimuth
    float glow  = pow(max(sun_dot, 0.0), 256.0);
    float haze  = pow(max(sun_dot, 0.0), 2.0) * 0.25;
    color += COLOR_SUNGLOW * (glow + haze);

    frag_color = vec4(color, 1.0);
}
