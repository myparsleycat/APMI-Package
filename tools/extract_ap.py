import argparse
import json
from ap_tools.extract import extract, inventory

parser = argparse.ArgumentParser(description="List or extract AP compute-skinned mesh components from a dump")
parser.add_argument('dump')
parser.add_argument('--out')
parser.add_argument('--ib', action='append', default=[])
parser.add_argument('--no-textures', action='store_true')
args = parser.parse_args()
if args.out:
    result = extract(args.dump, args.out, args.ib, textures=not args.no_textures)
    print(json.dumps({'project': args.out, 'components': len(result['components']), 'skipped': result['skipped']}))
else:
    _, groups, skipped = inventory(args.dump)
    print(json.dumps({'meshes': [dict(ib=g['key'][0], index_count=g['key'][1], first_index=g['key'][2],
                                     vertices=g['skin']['vertices'], influences=g['skin']['influences'],
                                     passes=[d.number for d in g['draws']]) for g in groups], 'skipped': skipped}, indent=2))
