import os,sys
if len(sys.argv)>1 and sys.argv[1]=='serve':
    import uvicorn
    uvicorn.run('serve:app',host='0.0.0.0',port=8080)
else:
    from train import train
    train(os.environ.get('SM_CHANNEL_DATASET','/opt/ml/input/data/dataset'),os.environ.get('SM_CHANNEL_ENCODER','/opt/ml/input/data/encoder'),os.environ.get('SM_MODEL_DIR','/opt/ml/model'),os.environ.get('TRAINING_JOB_NAME','sagemaker'))
