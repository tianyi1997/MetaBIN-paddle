import paddle
import paddle.nn as nn
import paddle.nn.functional as F
from .resnet import build_resnet_backbone
from .heads import MetalearningHead
from .losses import cross_entropy_loss, triplet_loss


class Metalearning(nn.Layer):
    def __init__(self, num_classes, pixel_mean=[123.675, 116.28, 103.53], pixel_std=[58.395, 57.120000000000005, 57.375],  name_scope=None, dtype="float32"):
        super().__init__(name_scope, dtype)
        pixel_mean = paddle.to_tensor(pixel_mean).unsqueeze((0, -1, -1))
        pixel_std = paddle.to_tensor(pixel_std).unsqueeze((0, -1, -1))
        self.register_buffer('pixel_mean', pixel_mean)
        self.register_buffer('pixel_std', pixel_std)
        self.backbone = build_resnet_backbone() # resnet-50
        self.heads = MetalearningHead(num_classes)


    def forward(self, batched_inputs, opt=None):
        if self.training:
            outs = dict()
            assert "targets" in batched_inputs, "Person ID annotation are missing in training!"
            outs['targets'] = batched_inputs["targets"].long().to(self.device)
            if 'domains' in batched_inputs.keys():
                outs['domains'] = batched_inputs['domains'].long().to(self.device)
            if outs['targets'].sum() < 0: outs['targets'].zero_()

            features = self.backbone(images, opt)
            result = self.heads(features, outs['targets'], opt)

            outs['outputs'] = result

            return outs
        else:
            images = self.preprocess_image(batched_inputs)
            features = self.backbone(images, opt)
            return self.heads(features)

    def preprocess_image(self, batched_inputs):
        """
        Normalize and batch the input images.
        """
        images = batched_inputs["images"].to(self.device)
        # images = batched_inputs
        images.sub_(self.pixel_mean).div_(self.pixel_std)
        return images


    def losses(self, outs, opt = None):
        outputs           = outs["outputs"]
        gt_labels         = outs["targets"]
        if 'domains' in outs.keys():
            domain_labels = outs['domains']
        else:
            domain_labels = None

        pred_class_logits = outputs['pred_class_logits'].detach()
        cls_outputs       = outputs['cls_outputs']
        pooled_features   = outputs['pooled_features']
        bn_features       = outputs['bn_features']
        loss_names = opt['loss']
        loss_dict = {}
        # log_accuracy(pred_class_logits, gt_labels) # Log prediction accuracy


        if "CrossEntropyLoss" in loss_names:
            loss_dict['loss_cls'] = cross_entropy_loss(
                cls_outputs,
                gt_labels,
                eps=0.1,
                alpha=0.2,
            ) * 1.0


        if "TripletLoss" in loss_names:
            loss_dict['loss_triplet'] = triplet_loss(
                pooled_features,
                gt_labels,
                margin=0.3,
                norm_feat=False,
                hard_mining=True,
                dist_type='euclidean',
                loss_type='logistic',
                domain_labels=domain_labels,
                pos_flag=[1, 0, 0],
                neg_flag=[0, 1, 1],
            ) * 1.0
        return loss_dict


