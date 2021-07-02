#!/bin/bash

##NECESSARY JOB SPECIFICATIONS for a parallel GPU job
#SBATCH --job-name=test_dqn_tianshou       #Set the job name to "JobExample5"
#SBATCH --time=03:00:00              #Set the wall clock limit to 1hr and 30min
#SBATCH --ntasks=1                   #Request 1 task
#SBATCH --mem=10G                  #Request 10GB per node
#SBATCH --output=dqn_tianshou.%j      #Send stdout/err to "Example5Out.[jobID]"
#SBATCH --gres=gpu:2                 #Request 2 GPU per node can be 1 or 2
#SBATCH --partition=gpu              #Request the GPU partition/queue

##OPTIONAL JOB SPECIFICATIONS
##SBATCH --account=122774970664             #Set billing account
##SBATCH --mail-type=ALL              #Send email on all job events
##SBATCH --mail-user=email_address    #Send all emails to email_address 

ml purge
# ADD udocker to path before loading
# export PATH=/scratch/yangyangfu/:$PATH
ml udocker
bash test_dqn_tianshou_udocker.sh