"""Record an explicit human decision; release promotion separately enforces approval."""
import boto3

def review(arn,decision,config,client=None):
    prefix=f"arn:aws:sagemaker:{config['region']}:{config['account_id']}:model-package/{config['model_package_group']}/"
    if not arn.startswith(prefix) or not arn[len(prefix):].isdigit():raise ValueError('Package must belong to this project model group')
    if decision not in {'Approved','Rejected'}:raise ValueError('Unsupported approval decision')
    sm=client or boto3.client('sagemaker',region_name=config['region'])
    package=sm.describe_model_package(ModelPackageName=arn)
    if package['ModelPackageStatus']!='Completed':raise ValueError('Package is not ready for review')
    sm.update_model_package(ModelPackageArn=arn,ModelApprovalStatus=decision)
    print('Recorded model review:',decision,arn)
