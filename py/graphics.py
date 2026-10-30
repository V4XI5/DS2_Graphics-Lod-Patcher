import json
import os
import struct
import sys

FMT = {'float': '<f', 'int': '<i', 'int32': '<i', 'uint32': '<I', 'uint16': '<H', 'uint8': '<B'}

LOD_SWITCH = 4.0
DRAW_NEAR = 3.0
DRAW_NEAR_LIMIT = 1000.0
DRAW_FAR = 2.0
DRAW_LIMIT = 2048.0
PLACEMENT = 2.0
TERRAIN_LOD = 2.0
TERRAIN_TABLE = 2.0
SWITCH_TO_MESH = 1.0
TERRAIN_SHADING_LAYERS = {}
TILE_HIGH_STEP = 2
TILE_MEDIUM_STEP = 4
INSTANCING = 2.0
SUN_CASCADES = 3
SUN_NEAR_SHADOWMAP = 4096
SUN_VOLUME_SAMPLES = 16
LIGHT_SHADOW_DIST = 2.0
LIGHT_FADE = 1.5
LIGHT_FILTER = {9: 16}
LIGHT_VOLUME = {4: 8}
OCEAN = 2.0
IMPACT = 2.0
IMPACT_LIMIT = 100.0


def leaves(attrs, pre=''):
    for a in attrs:
        name = pre + a['n']
        if 'attrs' in a:
            yield from leaves(a['attrs'], name + '.')
        elif 'items' in a:
            for i, it in enumerate(a['items']):
                if isinstance(it, dict) and 'attrs' in it:
                    yield from leaves(it['attrs'], f'{name}[{i}].')
                elif isinstance(it, list):
                    yield from leaves(it, f'{name}[{i}].')
        else:
            yield name, a


def read(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            yield json.loads(line)


class Builder:
    def __init__(self):
        self.patches = []
        self.counts = {}

    def set(self, obj, attr, new, what):
        fmt = FMT[attr['t']]
        if attr.get('pos') is None:
            raise ValueError(f'{obj["id"]} {what}: no position')
        old_b = struct.pack(fmt, attr['v'])
        new_b = struct.pack(fmt, new)
        if old_b == new_b:
            return
        self.patches.append({'file': obj['file'], 'pos': attr['pos'], 'old': old_b.hex(),
                             'new': new_b.hex(), 'note': f'{obj["id"]} {what}'})
        key = what.split('[')[0].split(' ')[0]
        self.counts[key] = self.counts.get(key, 0) + 1


def element(array_attr, i):
    return {'t': 'float', 'v': array_attr['v'][i], 'pos': array_attr['pos'] + 4 + 4 * i}


def draw_factor(distance):
    if 0 < distance < DRAW_NEAR_LIMIT:
        return DRAW_NEAR
    if DRAW_NEAR_LIMIT <= distance <= DRAW_LIMIT:
        return DRAW_FAR
    return 1.0


def tidy(v):
    bits = struct.unpack('<I', struct.pack('<f', v))[0]
    return struct.unpack('<f', struct.pack('<I', (bits + 0x8000) & 0xffff0000))[0]


def lod_meshes(b, scan):
    for o in read(os.path.join(scan, 'lodmesh.jsonl')):
        top = {a['n']: a for a in o['attrs']}
        max_a = top['MaxDistance']
        parts = [dict(leaves(p if isinstance(p, list) else p['attrs']))
                 for p in top['RuntimeMeshes'].get('items', [])]
        old_max = max_a['v']
        f_max = draw_factor(old_max)
        new_max = old_max * f_max
        limit = new_max if new_max > 0 else float('inf')
        dists = [p['Distance']['v'] for p in parts]
        last = max(dists, default=0.0)
        if last * LOD_SWITCH < limit:
            f_lod = LOD_SWITCH
        else:
            f_lod = max(f_max, min(LOD_SWITCH, 0.9 * limit / last))
        new_dists = [d * f_lod for d in dists]
        r_max = tidy(new_max) if f_max > 1 else new_max
        r_dists = [tidy(d) for d in new_dists] if f_lod > 1 else new_dists
        r_limit = r_max if r_max > 0 else float('inf')
        if all(d < r_limit for d in r_dists) or not all(d < limit for d in new_dists):
            new_max, new_dists = r_max, r_dists
        b.set(o, max_a, new_max, 'LodMesh.MaxDistance')
        for i, p in enumerate(parts):
            if p['Distance']['v'] > 0:
                b.set(o, p['Distance'], new_dists[i], f'LodMesh.Distance[{i}]')


def terrain_pass(b, o, d):
    n = sum(1 for k in d if k.endswith('].LODDistance'))
    dist = [d[f'LODDistances[{i}].LODDistance'] for i in range(n)]
    squared = d['LodDistancesSquared']
    old = [a['v'] for a in dist]
    for i, v in enumerate(old):
        if abs(squared['v'][i] - v * v) > 1e-3 * max(1.0, v * v):
            raise ValueError(f'{o["id"]}: LodDistancesSquared[{i}] does not match LODDistance')
    new = list(old)
    for i in range(n - 2, -1, -1):
        if old[i] > 1.0:
            v = min(old[i] * TERRAIN_TABLE, (old[i] + new[i + 1]) / 2)
            new[i] = struct.unpack('<f', struct.pack('<f', v))[0]
    if any(a >= c for a, c in zip(new, new[1:])):
        raise ValueError(f'{o["id"]}: scaled terrain LOD table out of order')
    for i, v in enumerate(new):
        b.set(o, dist[i], v, 'TerrainPass.LODDistance')
        b.set(o, element(squared, i), v * v, 'TerrainPass.LodDistancesSquared')
    switch = d['SwitchToMeshDistance']
    b.set(o, switch, switch['v'] * SWITCH_TO_MESH, 'TerrainPass.SwitchToMeshDistance')


def terrain_layers(b, o, d):
    n = sum(1 for k in d if k.endswith('].MaterialLayerIndex'))
    layers = [d[f'LODDistances[{i}].MaterialLayerIndex'] for i in range(n)]
    old = tuple(a['v'] for a in layers)
    if old not in TERRAIN_SHADING_LAYERS:
        raise ValueError(f'{o["id"]}: unexpected shading material layer table {old}')
    for a, v in zip(layers, TERRAIN_SHADING_LAYERS[old]):
        b.set(o, a, v, 'TerrainPass.MaterialLayerIndex')


def render(b, scan):
    for o in read(os.path.join(scan, 'render.jsonl')):
        if o['type'] == 'LevelSettings':
            a = next(x for x in o['attrs'] if x['n'] == 'MaxPlacementDistance')
            b.set(o, a, max(a['v'], 2048.0), 'LevelSettings.MaxPlacementDistance')

    shading = set()
    for o in read(os.path.join(scan, 'render2.jsonl')):
        if o['type'] == 'Terrain':
            ref = dict(leaves(o['attrs']))['ShadingPassSetup']['v']
            shading.add(':'.join(ref.split(':')[1:3]))

    for o in read(os.path.join(scan, 'render2.jsonl')):
        d = dict(leaves(o['attrs']))
        t = o['type']
        if t == 'MeshPlacement':
            a = d['MaxRenderDistance']
            if a['v'] >= 30:
                b.set(o, a, a['v'] * PLACEMENT, 'MeshPlacement.MaxRenderDistance')
        elif t == 'Terrain':
            a = d['LodDistanceScale']
            b.set(o, a, a['v'] * TERRAIN_LOD, 'Terrain.LodDistanceScale')
        elif t == 'TerrainRenderPassSetup':
            terrain_pass(b, o, d)
            if TERRAIN_SHADING_LAYERS and o['id'] in shading:
                terrain_layers(b, o, d)
        elif t == 'TileBasedStreamingStrategyResource':
            high, medium, low = (d[k] for k in ('HighLODDiameter', 'MediumLODDiameter', 'LowLODDiameter'))
            new_high, new_medium = high['v'] + TILE_HIGH_STEP, medium['v'] + TILE_MEDIUM_STEP
            if not new_high < new_medium < low['v']:
                raise ValueError(f'{o["id"]}: tile diameters out of order')
            b.set(o, high, new_high, 'Tiles.HighLODDiameter')
            b.set(o, medium, new_medium, 'Tiles.MediumLODDiameter')
        elif t == 'SunLightResource':
            count = d['CascadeCount']
            if count['v'] == 2:
                b.set(o, count, SUN_CASCADES, 'Sun.CascadeCount')
            near = d['CascadeSettings0.ShadowMapSize.Value']
            if near['v'] == 2048:
                b.set(o, near, SUN_NEAR_SHADOWMAP, 'Sun.Cascade0.ShadowMapSize')
            vol = d['VolumeLightSampleCount.Value']
            if 0 < vol['v'] < SUN_VOLUME_SAMPLES:
                b.set(o, vol, SUN_VOLUME_SAMPLES, 'Sun.VolumeLightSampleCount')
        elif t == 'WaveParticleManager':
            for k in ('SingletonLOD_FarCullDistance', 'SingletonLOD_UnpackDistanceStart',
                      'SingletonLOD_UnpackDistanceFinish', 'WavefrontLOD_FarCullDistance',
                      'WavefrontLOD_UnpackDistanceStart', 'WavefrontLOD_UnpackDistanceFinish',
                      'WavefrontLOD_RadiusDistanceStart', 'WavefrontLOD_RadiusDistanceFinish'):
                b.set(o, d[k], d[k]['v'] * OCEAN, f'Ocean.{k}')
        elif t == 'DSInstancingMeshResource':
            b.set(o, d['LodDistanceMultiplerScale'], 1.0, 'Instancing.LodDistanceMultiplerScale')
            b.set(o, d['MaxDistance'], d['MaxDistance']['v'] * INSTANCING, 'Instancing.MaxDistance')
            lods = d['LodDistances']
            for i, v in enumerate(lods['v']):
                b.set(o, element(lods, i), v * INSTANCING, 'Instancing.LodDistances')


def lights(b, scan):
    for o in read(os.path.join(scan, 'lights.jsonl')):
        d = dict(leaves(o['attrs']))
        if d['CastShadows.Value']['v']:
            for axis in ('X', 'Y'):
                a = d[f'StopShadowCastingDistanceRange.Value.{axis}']
                b.set(o, a, a['v'] * LIGHT_SHADOW_DIST, 'Light.StopShadowCastingDistance')
            for axis in ('X', 'Y', 'Z', 'W'):
                a = d[f'ShadowMapSizeLODDistances.Value.{axis}']
                b.set(o, a, a['v'] * LIGHT_SHADOW_DIST, 'Light.ShadowMapSizeLODDistance')
            a = d['FilterSamplesCount.Value']
            if a['v'] in LIGHT_FILTER:
                b.set(o, a, LIGHT_FILTER[a['v']], 'Light.FilterSamplesCount')
        for k in ('Min', 'Max'):
            a = d[f'DistanceFadeRange.Value.{k}']
            b.set(o, a, a['v'] * LIGHT_FADE, 'Light.DistanceFadeRange')
        a = d['VolumeLightSampleCount.Value']
        if a['v'] in LIGHT_VOLUME:
            b.set(o, a, LIGHT_VOLUME[a['v']], 'Light.VolumeLightSampleCount')


def impacts(b, scan):
    for o in read(os.path.join(scan, 'impacts.jsonl')):
        a = next(x for x in o['attrs'] if x['n'] == 'MaxDistanceToCamera')
        if 0 < a['v'] <= IMPACT_LIMIT:
            b.set(o, a, a['v'] * IMPACT, 'Impact.MaxDistanceToCamera')


def main():
    scan, out_path = sys.argv[1:3]
    exclude = set()
    if '--exclude' in sys.argv:
        with open(sys.argv[sys.argv.index('--exclude') + 1], encoding='utf-8') as f:
            exclude = {(p['file'], p['pos']) for p in json.load(f)}

    b = Builder()
    lod_meshes(b, scan)
    render(b, scan)
    lights(b, scan)
    impacts(b, scan)

    seen = set()
    for p in b.patches:
        key = (p['file'], p['pos'])
        if key in seen or key in exclude:
            sys.exit(f'overlapping patch at {key}: {p["note"]}')
        seen.add(key)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(b.patches, f, indent=0)
    for k, n in sorted(b.counts.items()):
        print(f'{n:7d}  {k}')
    print(f'{len(b.patches)} patches in {len({p["file"] for p in b.patches})} files -> {out_path}')


if __name__ == '__main__':
    main()
