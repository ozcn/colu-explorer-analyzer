# -*- coding: utf-8 -*-

import os
import csv
import json
from argparse import ArgumentParser
from urllib import request
from datetime import datetime
import time


def dt2ts(dt):
    return int(time.mktime(dt.timetuple()) * 1000) + (dt.microsecond // 1000)


def ts2dt(ts):
    return datetime.fromtimestamp(
        int(ts) // 1000
    ).replace(microsecond=(int(ts) % 1000 * 1000))


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('asset_id')
    parser.add_argument('names')
    parser.add_argument(
        '--base_url',
        default='https://explorer.coloredcoins.org/api/' +
        'getassetinfowithtransactions?assetId={}'
    )
    parser.add_argument(
        '--out_dir',
        default=None
    )
    args = parser.parse_args()
    with request.urlopen(args.base_url.format(args.asset_id)) as res:
        data = json.load(res)

    with open(args.names, 'r', encoding='utf-8') as fin:
        reader = csv.DictReader(fin)
        address_name_map = {
            d['address']: d['name'] for d in reader
        }

    tfs = data['transfers']
    holders = data['holders']
    address_amount_map = {d['address']: d['amount'] for d in holders}

    def tidy(tf):
        res = {}
        res['txid'] = tf['txid']
        res['timestamp'] = tf['blocktime']
        res['to'] = {
            'address': tf['vout'][0]['scriptPubKey']['addresses'][0],
            'amount': tf['vout'][0]['assets'][0]['amount']
        }
        res['from'] = {
            'before': [{
                'address': d['previousOutput']['addresses'][0],
                'amount': d['assets'][0]['amount']
            } for d in tf['vin'] if len(d['assets']) > 0],
            'after': [{
                'address': d['scriptPubKey']['addresses'][0],
                'amount': d['assets'][0]['amount']
            } for d in tf['vout'][1:] if len(d['assets']) > 0]
        }
        return res

    res = [tidy(d) for d in tfs]
    res.sort(key=lambda x: x['timestamp'])

    outdir = args.out_dir or 'output_{}_{}'.format(
        args.asset_id, dt2ts(datetime.now())
    )

    if not os.path.exists(outdir):
        os.makedirs(outdir)

    with open(os.path.join('graph.json'), 'w') as fout:
        json.dump(res, fout)

    address_rings = []
    for d in res:
        s = set([dd['address'] for dd in d['from']['before']] +
                [dd['address'] for dd in d['from']['after']])
        tmp = []
        for rng in address_rings:
            if len(rng.intersection(s)) != 0:
                s = s.union(rng)
            else:
                tmp.append(rng)
        address_rings = tmp + [s]

    for d in res:
        if len([dd for dd in address_rings if d['to']['address'] in dd]) == 0:
            address_rings.append(set([d['to']['address']]))

    idx_name_map = [None for i in range(len(address_rings))]
    for addr, name in address_name_map.items():
        nhits = 0
        for i, rng in enumerate(address_rings):
            if addr in rng:
                idx_name_map[i] = name
                nhits += 1
        if nhits != 1:
            print('nhit={}'.format(nhits), addr, name)

    nunknowns = 0
    for i, d in enumerate(idx_name_map):
        if d is None:
            nunknowns += 1
            idx_name_map[i] = 'unknown_{:02}'.format(nunknowns)

    address_idx_amount_map = {
        k: [(
            [i for i, ar in enumerate(address_rings) if k in ar] + [None]
        )[0], v] for k, v in address_amount_map.items()
    }

    address_name_amount_map = {
        k: [
            idx_name_map[v[0]], v[1]
        ] for (k, v) in address_idx_amount_map.items()
    }

    with open(os.path.join(
                outdir, 'result.tsv'
            ), 'w', encoding='utf-8') as fout:
        writer = csv.writer(fout, lineterminator='\n', delimiter='\t')
        writer.writerow(['name', 'amount', 'address'])
        writer.writerows(
            [[v[0], v[1], k] for (k, v) in sorted(
                address_name_amount_map.items(), key=lambda x: x[1][0]
            )]
        )

    address_walletno_map = {}

    for (i, s) in enumerate(address_rings):
        for a in s:
            address_walletno_map[a] = i

    with open(os.path.join(
                outdir, 'rings.tsv'
            ), 'w', encoding='utf-8') as fout:
        writer = csv.writer(fout, lineterminator='\n', delimiter='\t')
        writer.writerow(['ring_no', 'address', 'name', 'amount'])
        writer.writerows(
            [[
                v,
                k,
                idx_name_map[v],
                address_amount_map[k]
                if k in address_amount_map else None
            ] for (k, v) in address_walletno_map.items()]
        )

    complete_address_name_map = {
        k: idx_name_map[v] for (k, v) in address_walletno_map.items()
    }

    res2 = []
    for d in res:
        res2.append({
            'txid': d['txid'],
            'timestamp': d['timestamp'],
            'to': {
                'name': complete_address_name_map[d['to']['address']],
                'amount': d['to']['amount']
            },
            'from': {
                'name': list(set(
                    [
                        complete_address_name_map[a['address']]
                        for a in d['from']['before']
                    ] + [
                        complete_address_name_map[a['address']]
                        for a in d['from']['after']
                    ]))[0],
                'amount_before': sum(
                    [dd['amount'] for dd in d['from']['before']]
                ),
                'amount_after': sum(
                    [dd['amount'] for dd in d['from']['after']]
                )
            }
        })

    with open(os.path.join(
                outdir, 'graph.json'
            ), 'w', encoding='utf-8') as fout:
        json.dump(res2, fout)

    with open(os.path.join(
                outdir, 'social_map.tsv'
            ), 'w', encoding='utf-8') as fout:
        writer = csv.writer(fout, lineterminator='\n', delimiter='\t')
        writer.writerow([
            'txid', 'timestamp', 'to_name', 'to_amount',
            'from_name', 'from_amount_before', 'from_amount_after'
        ])
        writer.writerows([[
            d['txid'], ts2dt(d['timestamp']).strftime('%Y-%m-%d %H:%M:%S'),
            d['to']['name'], d['to']['amount'], d['from']['name'],
            d['from']['amount_before'], d['from']['amount_after']
        ] for d in res2])
