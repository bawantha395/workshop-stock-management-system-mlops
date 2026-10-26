"""Shared reviewed-dataset validation; no ML runtime dependency."""
def validate_manifest(rows):
    if len(rows)<60:raise ValueError('At least 60 reviewed workshop images are required')
    sessions={}
    for r in rows:
        if not all(r.get(k) for k in ['file','sku','session','split']):raise ValueError('Manifest requires file, sku, session, split')
        if r['split'] not in {'train','validation','test'}:raise ValueError('Invalid dataset split')
        if r['session'] in sessions and sessions[r['session']]!=r['split']:raise ValueError('Capture-session leakage across splits')
        sessions[r['session']]=r['split']
    for split in ['train','validation','test']:
        group=[r for r in rows if r['split']==split]
        if len(group)<15 or len({r['sku'] for r in group})<3:raise ValueError('Each split needs at least 15 images across at least 3 SKUs')

