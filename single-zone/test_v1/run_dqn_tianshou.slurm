#!/bin/bash

##NECESSARY JOB SPECIFICATIONS for a parallel GPU job
#SBATCH --job-name=tune_ddqn       #Set the job name to "JobExample5"
#SBATCH --time=2-12:00:00              #Set the wall clock limit to 1hr and 30min
#SBATCH --ntasks=324                   #Request 1 task
#SBATCH --ntasks-per-node=20
#SBATCH --mem=40G                  #Request 10GB per node
#SBATCH --output=log_tune_ddqn.%j      #Send stdout/err to "Example5Out.[jobId]

##OPTIONAL JOB SPECIFICATIONS
##SBATCH --account=122774970664             #Set billing account
##SBATCH --mail-type=ALL              #Send email on all job events
##SBATCH --mail-user=yangyang.fu@tamu.edu    #Send all emails to email_address 

ml purge
module load CUDA
# ADD udocker to path before loading
echo "Define udocker path!!!!"
export UDOCKER_DIR=$SCRATCH/udocker
export PATH=$UDOCKER_DIR:$PATH
#ml udocker
# define a container name
export CONTAINER_ID=dqn_v1_fan
# create a container
echo "creat a DRL container!!!!!!"
udocker create --name=$CONTAINER_ID yangyangfu/mpcdrl:debug
# prepare udocker to access gpu
echo "setup for GPU application!!!!!!"
udocker setup --force --nvidia $CONTAINER_ID
# run experiment
echo "run DRL experiment in Docker"
udocker run --user=root -e DISPLAY=${DISPLAY} -v /tmp/.X11-unix:/tmp/.X11-unix:rw -v `pwd`:/mnt/shared $CONTAINER_ID /bin/bash -c "source activate base && export PYTHONPATH=$PYFMI_PY3_CONDA_PATH:$PYTHONPATH && cd /mnt/shared && python /mnt/shared/test_ddqn_tianshou.py"
# remove container after experiment
udocker rm $CONTAINER_ID
#bash test_dqn_tianshou_udocker.sh
