import os,sys
if len(sys.argv)>1 and sys.argv[1]=='serve':
    import uvicorn
    uvicorn.run('serve:app',host='0.0.0.0',port=8080)
else:
    import json
    from pathlib import Path
    config=Path("/opt/ml/input/config/hyperparameters.json")
    parameters=json.loads(config.read_text()) if config.exists() else {}
    demo_mode=parameters.get('demo_mode')=='true'
    benchmark_mode=parameters.get('benchmark_mode')=='true'
    if parameters.get('task')=='monthly_car_parts_benchmark':
        if not benchmark_mode:raise ValueError('Monthly public data requires explicit benchmark mode')
        from monthly_parts_benchmark import main
        main();sys.exit(0)
    if parameters.get("task")=="stock_forecast":
        from forecast import main
        main(demo_mode=demo_mode);sys.exit(0)
    from train import train
    train(os.environ.get('SM_CHANNEL_DATASET','/opt/ml/input/data/dataset'),os.environ.get('SM_CHANNEL_ENCODER','/opt/ml/input/data/encoder'),os.environ.get('SM_MODEL_DIR','/opt/ml/model'),os.environ.get('TRAINING_JOB_NAME','sagemaker'),demo_mode=demo_mode,benchmark_mode=benchmark_mode)
