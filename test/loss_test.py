import paddle
import torch
import numpy as np
from reprod_log import ReprodLogger, ReprodDiffHelper
import random
import sys
sys.path.append('.')
from utils import translate_weight, build_ref_model, translate_inputs_p2t
from modeling import Metalearning
from data import build_train_loader_for_m_resnet
from tqdm import tqdm

def loss_test():
    paddle.device.set_device('gpu:0')

    seed = 2022
    np.random.seed(seed)
    random.seed(seed)

    reprod_log_ref = ReprodLogger()
    reprod_log_pad = ReprodLogger()

    torch_path = "./model_weights/model.pth"
    paddle_path = "./model_weights/model.pdparams"

    model_ref = build_ref_model(num_classes=4).cuda()
 #   model_ref.eval()

    torch.save(model_ref.state_dict(), torch_path)
#
    translate_weight(torch_path, paddle_path)
    model_pad = Metalearning(num_classes=4)
    model_pad.set_state_dict(paddle.load(paddle_path))
 #   model_pad.eval()

    train_loader, mtrain_loader, mtest_loader, num_domains = build_train_loader_for_m_resnet(['LiteData'], batch_size=16, num_workers=0)
    for i in tqdm(range(5)):
        inputs_pad = next(train_loader.__iter__())
        inputs_ref = translate_inputs_p2t(inputs_pad)

        outputs_ref = model_ref(inputs_ref, {'param_update': False, 'loss': ('CrossEntropyLoss', 'TripletLoss', 'SCT', ), 'type_running_stats': 'general', 'each_domain': False})
        losses_ref = model_ref.losses(outputs_ref, opt={'loss':['CrossEntropyLoss', 'TripletLoss', 'SCT']})

        reprod_log_ref.add("CEloss_%d"%(i), losses_ref['loss_cls'].cpu().detach().numpy())
        reprod_log_ref.add("Tripletloss_%d"%(i), losses_ref['loss_triplet'].cpu().detach().numpy())
        reprod_log_ref.add("SCT_%d"%(i), losses_ref['loss_stc'].cpu().detach().numpy())

        outputs_pad = model_pad(inputs_pad, {'param_update': False, 'loss': ('CrossEntropyLoss', 'TripletLoss', 'SCT'), 'type_running_stats': 'general', 'each_domain': False})
        losses_pad = model_pad.losses(outputs_pad, opt={'loss':['CrossEntropyLoss', 'TripletLoss', 'SCT']})

        reprod_log_pad.add("CEloss_%d"%(i), losses_pad['loss_cls'].cpu().detach().numpy())
        reprod_log_pad.add("Tripletloss_%d"%(i), losses_pad['loss_triplet'].cpu().detach().numpy())
        reprod_log_pad.add("SCT_%d"%(i), losses_pad['loss_stc'].cpu().detach().numpy())

        del outputs_pad, outputs_ref, losses_ref, losses_pad, inputs_ref
    reprod_log_ref.save('./result/loss_ref.npy')
    reprod_log_pad.save('./result/loss_paddle.npy')

    diff_helper = ReprodDiffHelper()

    info1 = diff_helper.load_info("./result/loss_paddle.npy")
    info2 = diff_helper.load_info("./result/loss_ref.npy")

    diff_helper.compare_info(info1, info2)

    diff_helper.report(
        diff_method="mean", diff_threshold=1e-6, path="./result/log/loss_diff.log")

if __name__ == '__main__':
    loss_test()
