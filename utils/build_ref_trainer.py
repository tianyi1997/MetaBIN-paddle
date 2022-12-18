#!/usr/bin/env python
# encoding: utf-8
"""
@author:  sherlock
@contact: sherlockliao01@gmail.com
"""

import logging
import os
import sys
import re

sys.path.append('./refs')

from refs.fastreid.config import get_cfg
from refs.fastreid.engine import DefaultTrainer, default_argument_parser, default_setup, launch
from refs.fastreid.utils.checkpoint import Checkpointer
from refs.fastreid.engine import hooks
from refs.fastreid.evaluation import ReidEvaluator
from refs.fastreid.utils.file_io import PathManager
import torch
import numpy as np
import random
import glob


class Trainer(DefaultTrainer):
    @classmethod
    def build_evaluator(cls, cfg, num_query, output_folder=None):
        if output_folder is None:
            output_folder = os.path.join(cfg.OUTPUT_DIR, "inference")
        return ReidEvaluator(cfg, num_query)


def setup(args):
    """
    Create configs and perform basic setups.
    """
    cfg = get_cfg()

    # automatic OUTPUT dir
    cfg.merge_from_file(args.config_file)
    config_file_name = args.config_file.split('/')
    for i, x in enumerate(config_file_name):
        if x == 'configs':
            config_file_name[i] = 'logs'
        if '.yml' in x:
            config_file_name[i] = config_file_name[i][:-4]
    cfg.OUTPUT_DIR = '/'.join(config_file_name)

    cfg.merge_from_list(args.opts)
    cfg.freeze()

    if args.eval_only or args.dist_only or args.tsne_only or args.domain_only:
        if args.eval_only:
            tmp = 'eval'
        if args.dist_only:
            tmp = 'dist'
        if args.tsne_only:
            tmp = 'tsne'
        if args.domain_only:
            tmp = 'domain'
        default_setup(cfg, args, tmp=tmp)
    else:
        default_setup(cfg, args)
    return cfg

def build_ref_trainer(num_classes, batch_size, train_dataset=['Market1501'], test_dataset=['Market1501', 'DukeMTMC']):
    args = default_argument_parser().parse_args()
    args.config_file = './refs/configs/Sample/M-resnet.yml'
    args.eval_only = True
    args.resume = True
    cfg = setup(args)
    print("Command Line Args:", args)

    # cfg.MODEL.WEIGHTS = "./logs/Visualize/u01/model_final.pth"
    # Trainer.resume_or_load(cfg.MODEL.WEIGHTS, resume=args.resume)
    cfg.defrost()
    cfg.DATASETS.NAMES = train_dataset
    cfg.DATASETS.TESTS = test_dataset
    cfg.DATALOADER.NUM_WORKERS = 0
    cfg.SOLVER.IMS_PER_BATCH = batch_size
    cfg.MODEL.BACKBONE.PRETRAIN = False
    cfg.MODEL.HEADS.NUM_CLASSES = num_classes
    trainer = Trainer(cfg)
#    trainer.resume_or_load(resume=args.resume)
    return trainer

