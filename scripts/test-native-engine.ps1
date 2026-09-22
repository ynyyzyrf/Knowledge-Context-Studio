$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$validationRoot = Join-Path (Split-Path -Parent $projectRoot) 'validation'
$testImage = (Get-Content -Raw (Join-Path $validationRoot 'evidence/native-images.json') | ConvertFrom-Json).tests
$evidenceRoot = Join-Path $projectRoot 'runtime/native-context'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$dockerArgs = @('run','--rm','--network','none','--cpus','2','--memory','4g',
  '--env','OPENVIKING_CONFIG_FILE=/validation-tests/ov.conf',
  '--env','G0_EVENT_FILE=native-context-events.jsonl', '--env','PYTHONPATH=/product/src:/validation-tests',
  '--mount',"type=bind,source=$evidenceRoot,target=/evidence",
  '--mount',"type=bind,source=$projectRoot,target=/product,readonly",
  '--mount',"type=bind,source=$validationRoot\ov.test.conf,target=/validation-tests/ov.conf,readonly",
  '--mount',"type=bind,source=$validationRoot\worktrees\openviking-g0\tests,target=/validation-tests/tests,readonly",
  '--mount',"type=bind,source=$validationRoot\g0_model_fixture.py,target=/validation-tests/g0_model_fixture.py,readonly",
  '--mount',"type=bind,source=$validationRoot\test_http_contract.py,target=/validation-tests/test_http_contract.py,readonly",
  '--entrypoint','/app/.venv/bin/python',$testImage,'-m','pytest','-p','g0_model_fixture','-o','addopts=',
  '/product/integration/test_native_engine.py','-q','--junitxml=/evidence/native-context.xml')
& docker @dockerArgs *> (Join-Path $evidenceRoot 'result.txt')
$testExit = $LASTEXITCODE
Get-Content (Join-Path $evidenceRoot 'result.txt') -Tail 24
exit $testExit
