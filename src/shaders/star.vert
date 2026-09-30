#version 300 es
// Full-screen triangle for star.frag (no vertex buffer needed: draw 3 vertices).
// The CPU evaluator in src/render.c needs no counterpart: it visits every pixel.
void main() {
    vec2 position = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(position * 2.0 - 1.0, 0.0, 1.0);
}
