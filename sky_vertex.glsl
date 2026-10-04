/* -*- c -*- */

#version 420

// Full-screen-triangle trick: no VBO/attributes needed at all. For
// gl_VertexID 0,1,2 this produces (0,0), (2,0), (0,2) in [0,2] space, i.e.
// a single triangle that covers the whole [-1,1] NDC square (and then
// some, which gets clipped) with no seam down the middle like a two-
// triangle quad would have
out vec2 ndc;

void main(void)
{
    vec2 pos = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    ndc = pos * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
}
