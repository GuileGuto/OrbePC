"""
OrbePC -- case estilo "pebble/wedge", corpo unico e compacto (sem haste
fina a mostra), parecido com a foto de referencia: base larga arredondada
que sobe em curva continua ate a "cabeça" redonda do display, meio
afunilando pra tras. ESP32-C3 alojado dentro do corpo, conector USB-C
saindo pela parte de TRAS (horizontal, baixo, perto da mesa).

Duas pecas imprimiveis:
  1) corpo.stl  -- corpo principal (loft da base ate a cabeça) com o
                   bolso do ESP32-C3 e o recorte do USB-C na parede de tras.
  2) bezel.stl  -- anel frontal com o rebaixo pro display, fecha a
                   concha com 4 parafusos.
"""

import math
import cadquery as cq

# ----------------------------------------------------------------------
# PARAMETROS (mm / graus)
# ----------------------------------------------------------------------

# --- display redondo ---
DISPLAY_OD       = 38.0
DISPLAY_WINDOW   = 35.5
DISPLAY_POCKET_D = DISPLAY_OD + 0.6
DISPLAY_POCKET_H = 2.0
DISPLAY_THICK    = 9.0

# --- ESP32-C3 Super Mini ---
ESP_L = 24.0
ESP_W = 18.5
ESP_T = 4.0
ESP_CLR_L = 3.0
ESP_CLR_W = 2.0
ESP_CLR_T = 2.5

# --- corpo/concha (a "cabeça" que segura o display) ---
HEAD_OD       = 60.0
HEAD_WALL     = 2.4
HEAD_DEPTH    = 20.0
BEZEL_DEPTH   = 6.0
TILT_DEG      = 16.0     # inclinacao da TELA (so a orientacao da face)

# --- posicao do CENTRO da cabeça, direto em coordenadas (nao mais "haste
#     esticada" -- a cabeça fica quase em cima da base, soh com uma leve
#     inclinacao pra frente, igual a foto de referencia) ---
CASE_HEIGHT  = 50.0   # altura (Z) do centro da cabeça
HEAD_LEAN_Y  = 6.0     # quanto o centro da cabeça avanca pra frente (+Y)

# --- pegada da base (retangulo arredondado no chao) ---
BASE_W = 58.0
BASE_FRONT = 14.0     # quanto a base avanca na frente do centro
BASE_BACK  = -42.0    # quanto a base se estende pra tras (rabo curto)
BASE_FILLET = 13.0    # cantos bem arredondados -- visual "pebble"

# --- saida do cabo USB-C pela parte de TRAS (horizontal, baixa) ---
CONN_W = 10.0
CONN_H = 5.0
POCKET_BOTTOM_Y = -22.0   # posicao (Y) do fundo do bolso do ESP32, perto de tras
POCKET_BOTTOM_Z = 4.0     # um pouco acima da mesa

# --- parafusos do bezel ---
SCREW_PILOT_D = 2.0
SCREW_HEAD_CLEAR_D = 4.0
SCREW_RADIUS = HEAD_OD / 2 - 5.0

# ----------------------------------------------------------------------
theta = math.radians(TILT_DEG)
normal_dir = (0.0, math.cos(theta), math.sin(theta))  # so orientacao da face
x_dir = (1.0, 0.0, 0.0)

base_ref = (0.0, 0.0, 0.0)
head_origin = (0.0, HEAD_LEAN_Y, CASE_HEIGHT)
bezel_origin = tuple(head_origin[i] + HEAD_DEPTH * normal_dir[i] for i in range(3))

head_plane = cq.Plane(origin=head_origin, xDir=x_dir, normal=normal_dir)
bezel_plane = cq.Plane(origin=bezel_origin, xDir=x_dir, normal=normal_dir)

# ----------------------------------------------------------------------
# CORPO -- loft continuo da base ate o circulo da cabeça
# ----------------------------------------------------------------------
base_len = BASE_FRONT - BASE_BACK
base_slab = (
    cq.Workplane("XY")
    .center(0, (BASE_FRONT + BASE_BACK) / 2)
    .rect(BASE_W, base_len)
    .extrude(2)
)
base_slab = base_slab.edges("|Z").fillet(BASE_FILLET)
base_wire = base_slab.faces("<Z").wires().val()
head_wire = cq.Workplane(head_plane).circle(HEAD_OD / 2).val()

loft_solid = cq.Solid.makeLoft([base_wire, head_wire])
corpo = cq.Workplane(obj=loft_solid).union(base_slab)

# ----------------------------------------------------------------------
# CONCHA -- copo raso na "cabeça", aberto na frente pro display
# ----------------------------------------------------------------------
head_outer = cq.Workplane(head_plane).circle(HEAD_OD / 2).extrude(HEAD_DEPTH)
head_cavity = (
    cq.Workplane(head_plane)
    .workplane(offset=HEAD_WALL)
    .circle(HEAD_OD / 2 - HEAD_WALL)
    .extrude(HEAD_DEPTH)
)
head_shell = head_outer.cut(head_cavity)

pts = [
    (SCREW_RADIUS * math.cos(math.radians(a)), SCREW_RADIUS * math.sin(math.radians(a)))
    for a in (45, 135, 225, 315)
]
screw_holes = cq.Workplane(bezel_plane).pushPoints(pts).circle(SCREW_PILOT_D / 2).extrude(-8)
head_shell = head_shell.cut(screw_holes)

corpo = corpo.union(head_shell)

# ----------------------------------------------------------------------
# BOLSO DO ESP32-C3 -- segue o "espinhaço" do corpo: de um ponto baixo
# perto de tras ate dentro da cavidade da cabeça (acesso pela frente,
# com o bezel removido, pra deslizar a placa pra dentro)
# ----------------------------------------------------------------------
pocket_w = ESP_W + ESP_CLR_W
pocket_t = ESP_T + ESP_CLR_T

pocket_bottom = (0.0, POCKET_BOTTOM_Y, POCKET_BOTTOM_Z)
pocket_top = tuple(head_origin[i] + HEAD_WALL * normal_dir[i] + 3 * normal_dir[i] for i in range(3))
pocket_vec = tuple(pocket_top[i] - pocket_bottom[i] for i in range(3))
pocket_len = math.sqrt(sum(v * v for v in pocket_vec))
pocket_dir = tuple(v / pocket_len for v in pocket_vec)

pocket_plane = cq.Plane(origin=pocket_bottom, xDir=x_dir, normal=pocket_dir)
esp_pocket = cq.Workplane(pocket_plane).rect(pocket_w, pocket_t).extrude(pocket_len)
corpo = corpo.cut(esp_pocket)

# ----------------------------------------------------------------------
# RECORTE DO USB-C -- horizontal, saindo pela parede de TRAS, na altura
# do fundo do bolso. Corta de bem alem da casca pra dentro, garantindo
# que atravessa a parede seja qual for a inclinacao dela ali.
# ----------------------------------------------------------------------
conn_origin = (0.0, POCKET_BOTTOM_Y + 8.0, POCKET_BOTTOM_Z)
conn_plane = cq.Plane(origin=conn_origin, xDir=(1, 0, 0), normal=(0, -1, 0))
usb_cutter = cq.Workplane(conn_plane).rect(CONN_W, CONN_H).extrude(300)
corpo = corpo.cut(usb_cutter)

# ----------------------------------------------------------------------
# BEZEL
# ----------------------------------------------------------------------
bezel_outer = cq.Workplane(bezel_plane).circle(HEAD_OD / 2).extrude(BEZEL_DEPTH)
bezel_window = cq.Workplane(bezel_plane).circle(DISPLAY_WINDOW / 2).extrude(BEZEL_DEPTH + 2)
bezel_pocket = (
    cq.Workplane(bezel_plane)
    .workplane(offset=BEZEL_DEPTH - DISPLAY_POCKET_H)
    .circle(DISPLAY_POCKET_D / 2)
    .extrude(DISPLAY_POCKET_H + 2)
)
bezel = bezel_outer.cut(bezel_window).cut(bezel_pocket)

bezel_screw_holes = (
    cq.Workplane(bezel_plane).pushPoints(pts).circle(SCREW_HEAD_CLEAR_D / 2).extrude(BEZEL_DEPTH)
)
bezel = bezel.cut(bezel_screw_holes)

# ----------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------
cq.exporters.export(corpo, "corpo.stl")
cq.exporters.export(bezel, "bezel.stl")

assembly = corpo.union(bezel)
cq.exporters.export(assembly, "conjunto_preview.stl")

print("OK exportado: corpo.stl, bezel.stl, conjunto_preview.stl")
print("pocket_len=%.1f pocket_dir=%s" % (pocket_len, pocket_dir))
