#!/usr/bin/env python
import sys

import pandas as pd

filename, artifact = sys.argv[1:3]

iter_csv = pd.read_csv(sys.stdin if filename == '-' else filename, parse_dates=True, chunksize=1000)

df = pd.concat((chunk[chunk['Artifact'] == artifact] for chunk in iter_csv))

print('Sum of deltas:')
print(df.filter(regex='(delta|Author)', axis='columns').rename(
    columns={c: c.replace('(delta)', '') for c in df.columns}).groupby('Author').agg(
    ['sum', 'count']))
