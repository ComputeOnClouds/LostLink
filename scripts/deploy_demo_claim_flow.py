#!/usr/bin/env python3
"""Deploy the reviewed demo bundle from AWS CloudShell; preserve config and backups.

Run from the extracted release directory in the signed-in AWS console.
Only updates the Claims Lambda code and static app; no infrastructure changes.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

REGION = 'ap-southeast-1'
DISTRIBUTION = 'E1Z1ET4OC8QV3L'
DOMAIN = 'd14j9ujywx75yh.cloudfront.net'
BUCKET = 'lostlink-frontend-683803165839'
FUNCTION = 'LostLink-ClaimsFn'
API_ID = 'inx7guatn6'
ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DIST = ROOT / 'dist' if (ROOT / 'dist').is_dir() else PROJECT / 'frontend' / 'dist'
PATCH = ROOT / 'claims_handler.py' if (ROOT / 'claims_handler.py').is_file() else PROJECT / 'backend' / 'api' / 'claims_handler.py'
BACKUP = ROOT / ('backup-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()))


def aws(*args, json_result=False):
    result = subprocess.run(['aws', '--region', REGION, '--no-cli-pager', *args],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if json_result else result.stdout


def main():
    distribution = aws('cloudfront', 'get-distribution', '--id', DISTRIBUTION, json_result=True)['Distribution']
    assert distribution['DomainName'] == DOMAIN, 'Unexpected distribution'
    origin = distribution['DistributionConfig']['Origins']['Items'][0]['DomainName']
    assert origin.startswith(BUCKET + '.s3.'), 'Unexpected frontend bucket'
    integrations = aws('apigatewayv2', 'get-integrations', '--api-id', API_ID, json_result=True)['Items']
    assert any(i.get('IntegrationUri', '').endswith(':function:' + FUNCTION) for i in integrations)
    function = aws('lambda', 'get-function', '--function-name', FUNCTION, json_result=True)
    assert function['Configuration']['Handler'] == 'api.claims_handler.handler'
    BACKUP.mkdir()
    urllib.request.urlretrieve(function['Code']['Location'], BACKUP / 'claims-before.zip')
    aws('s3', 'cp', 's3://' + BUCKET + '/index.html', str(BACKUP / 'index-before.html'))
    aws('s3', 'cp', 's3://' + BUCKET + '/config.json', str(BACKUP / 'config-before.json'))
    patch = PATCH.read_bytes()
    with zipfile.ZipFile(BACKUP / 'claims-before.zip') as source:
        assert 'api/claims_handler.py' in source.namelist()
        with zipfile.ZipFile(ROOT / 'claims-updated.zip', 'w', zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(entry, patch if entry.filename == 'api/claims_handler.py' else source.read(entry.filename))
    rollback = f'''#!/bin/bash
set -euo pipefail
aws lambda update-function-code --region {REGION} --function-name {FUNCTION} --zip-file fileb://{BACKUP}/claims-before.zip --no-cli-pager >/dev/null
aws lambda wait function-updated --region {REGION} --function-name {FUNCTION}
aws s3 cp {BACKUP}/index-before.html s3://{BUCKET}/index.html --content-type text/html --cache-control no-cache
aws cloudfront create-invalidation --distribution-id {DISTRIBUTION} --paths '/*' --no-cli-pager
'''
    (BACKUP / 'rollback.sh').write_text(rollback)
    print('Backup and rollback script:', BACKUP, flush=True)
    aws('lambda', 'update-function-code', '--function-name', FUNCTION,
        '--revision-id', function['Configuration']['RevisionId'],
        '--zip-file', 'fileb://' + str(ROOT / 'claims-updated.zip'))
    aws('lambda', 'wait', 'function-updated', '--function-name', FUNCTION)
    status = aws('lambda', 'get-function-configuration', '--function-name', FUNCTION, json_result=True)
    assert status['LastUpdateStatus'] == 'Successful'
    print('Claims Lambda updated successfully', flush=True)
    # Upload immutable assets first, then switch HTML. Keep config.json and old assets.
    aws('s3', 'cp', str(DIST / 'assets'), 's3://' + BUCKET + '/assets/',
        '--recursive', '--cache-control', 'public,max-age=31536000,immutable')
    aws('s3', 'cp', str(DIST / 'index.html'), 's3://' + BUCKET + '/index.html',
        '--content-type', 'text/html', '--cache-control', 'no-cache')
    invalidation = aws('cloudfront', 'create-invalidation', '--distribution-id', DISTRIBUTION,
                       '--paths', '/*', json_result=True)['Invalidation']
    print('Frontend uploaded. Invalidation:', invalidation['Id'], flush=True)
    (ROOT / 'deployment-result.json').write_text(json.dumps(dict(
        distribution=DISTRIBUTION, invalidation=invalidation['Id'], backup=str(BACKUP),
        function=FUNCTION, codeSha256=status['CodeSha256']), indent=2))
    print('DEPLOYED https://' + DOMAIN, flush=True)


if __name__ == '__main__':
    main()
