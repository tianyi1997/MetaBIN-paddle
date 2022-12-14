import paddle
import paddle.nn as nn
import paddle.nn.functional as F
import math
import copy

def update_parameter(param, step_size, opt = None):
    """
    TODO debug
    """
    loss = opt['meta_loss']
    use_second_order = opt['use_second_order']
    allow_unused = opt['allow_unused']
    stop_gradient = opt['stop_gradient']
    flag_update = False
    assert not use_second_order, 'Use second order!' 
    if step_size is not None:
        if not stop_gradient:
            if param is not None:
                if opt['auto_grad_outside']:
                    if opt['grad_params'][0] is None:
                        del opt['grad_params'][0]
                        updated_param = param
                    else:
                        # print("[GRAD]{} [PARAM]{}".format(opt['grad_params'][0].data.shape, param.data.shape))
                        # outer
                        updated_param = param - step_size * opt['grad_params'][0]
                        del opt['grad_params'][0]
                else:
                    # inner
                    grad = paddle.grad(loss, param, create_graph=use_second_order, allow_unused=allow_unused)[0]
                    updated_param = param - step_size * grad
                # outer update
                # updated_param = opt['grad_params'][0]
                # del opt['grad_params'][0]
                flag_update = True
        else:
            if param is not None:

                if opt['auto_grad_outside']:
                    if opt['grad_params'][0] is None:
                        del opt['grad_params'][0]
                        updated_param = param
                    else:
                        # print("[GRAD]{} [PARAM]{}".format(opt['grad_params'][0].data.shape, param.data.shape))
                        # outer
                        updated_param = param - step_size * opt['grad_params'][0]
                        del opt['grad_params'][0]
                else:   # not used
                    # inner
                    # grad = Variable(autograd.grad(loss, param, create_graph=use_second_order, allow_unused=allow_unused)[0].data, requires_grad=False)
                    grad = paddle.grad(loss, param, create_graph=use_second_order, allow_unused=allow_unused)[0]
                    updated_param = param - step_size * grad
                # outer update
                # updated_param = opt['grad_params'][0]
                # del opt['grad_params'][0]
                flag_update = True
    if not flag_update:
        return param
    return updated_param


class meta_linear(nn.Linear):
    def __init__(self, in_features, out_features, weight_attr=None, bias_attr=None, name=None):
        if weight_attr is None:
            weight_attr=nn.initializer.KaimingUniform(negative_slope=math.sqrt(5), nonlinearity='leaky_relu')
        super().__init__(in_features, out_features, weight_attr, bias_attr, name)

    def forward(self, input, opt = None):
        if opt != None:
            use_meta_learning = False
            if opt['param_update']:
                if self.weight is not None:
                    if self.compute_meta_params:
                        use_meta_learning = True
        else:
            use_meta_learning = False
        if use_meta_learning:
            updated_weight = update_parameter(self.weight, self.w_step_size, opt)
            updated_bias = update_parameter(self.bias, self.b_step_size, opt)
            return F.linear(input, updated_weight, updated_bias)
        else:
            return F.linear(input, self.weight, self.bias)


class meta_conv2d(nn.Conv2D):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1, groups=1, padding_mode='zeros', weight_attr=None, bias_attr=None, data_format="NCHW"):
        super().__init__(in_channels, out_channels, kernel_size, stride, padding, dilation, groups, padding_mode, weight_attr, bias_attr, data_format)
    
    def forward(self, inputs, opt = None):
        if opt != None:
            use_meta_learning = False
            if opt['param_update']:
                if self.weight is not None:
                    if self.compute_meta_params:
                        use_meta_learning = True
        else:
            use_meta_learning = False
        if use_meta_learning:
            updated_weight = update_parameter(self.weight, self.w_step_size, opt)
            updated_bias = update_parameter(self.bias, self.b_step_size, opt)
            # print('meta_conv is computed')
            return F.conv2d(inputs, updated_weight, updated_bias, self._stride, self._padding, self._dilation, self._groups)
        else:
            return F.conv2d(inputs, self.weight, self.bias, self._stride, self._padding, self._dilation, self._groups)


def meta_norm(norm, out_channels, norm_opt, **kwargs):
    if isinstance(norm, str):
        if len(norm) == 0:
            return None
        norm = {
            "BN": meta_bn(out_channels, norm_opt, **kwargs),
            "IN": meta_in(out_channels, norm_opt, **kwargs),
            "BIN_gate2": meta_bin(out_channels, norm_opt, **kwargs),
        }[norm]
    return norm


class meta_bin(nn.Layer):
    def __init__(self, num_features, norm_opt = None, **kwargs):
        super().__init__()
        self.bat_n = meta_bn(num_features, norm_opt, **kwargs)
        self.ins_n = meta_in(num_features, norm_opt, **kwargs)
        if norm_opt['BIN_INIT'] == 'one':
            gate_init = nn.initializer.Constant(1)
        elif norm_opt['BIN_INIT'] == 'zero':
            gate_init = nn.initializer.Constant(0)
        elif norm_opt['BIN_INIT'] == 'half':
            gate_init = nn.initializer.Constant(0.5)
        elif norm_opt['BIN_INIT'] == 'random':
            gate_init = nn.initializer.Uniform(0, 1)
        self.gate = paddle.create_parameter([num_features], dtype='float32', default_initializer=gate_init)
        setattr(self.gate, 'bin_gate', True)

    def forward(self, inputs, opt=None):
        if inputs.dim() != 4:
            raise ValueError('expected 4D input (got {}D input)'.format(inputs.dim()))
        if opt != None:
            use_meta_learning_gates = False
            if opt['param_update']:
                if self.compute_meta_gates:
                    use_meta_learning_gates = True
        else:
            use_meta_learning_gates = False

        if use_meta_learning_gates:
            update_gate = update_parameter(self.gate, self.g_step_size, opt)
            if opt['inner_clamp']:
                # update_gate.data.clamp_(min=0, max=1)
                update_gate = update_gate.clip(min=0, max=1)
            # print(update_gate[0].data.cpu())
        else:
            update_gate = self.gate
        out_bn = self.bat_n(inputs, opt)
        out_in = self.ins_n(inputs, opt)
        update_gate = update_gate.unsqueeze([0, -1, -1]).astype(out_bn.dtype)
        out = out_bn * update_gate + out_in * (1-update_gate)
        return out


class meta_bn(nn.BatchNorm2D):
    def __init__(self, num_features, norm_opt, momentum=0.9, epsilon=1e-05,
                weight_freeze = False, bias_freeze = False,
                data_format='NCHW', use_global_stats=None, name=None):
        if not weight_freeze:
            weight_freeze = norm_opt['BN_W_FREEZE']
        if not bias_freeze:
            bias_freeze = norm_opt['BN_B_FREEZE']
        use_global_stats = norm_opt['BN_RUNNING']
        self.affine = False
        super().__init__(num_features, momentum, epsilon, None, None, data_format, use_global_stats, name)
        self.weight.stop_gradient = weight_freeze
        self.bias.stop_gradient = bias_freeze

    def forward(self, inputs, opt=None):
        if inputs.dim() != 4:
            raise ValueError('expected 4D input (got {}D input)'.format(inputs.dim()))
        if opt != None:
            use_meta_learning = False
            if opt['param_update']:
                if self.weight is not None:
                    if self.compute_meta_params:
                        use_meta_learning = True
        else:
            use_meta_learning = False

        if self.training:
            norm_type = opt['type_running_stats']
        else:
            norm_type = "eval"

        if use_meta_learning and self.affine:
            # if opt['zero_grad']: self.zero_grad()
            updated_weight = update_parameter(self.weight, self.w_step_size, opt)
            updated_bias = update_parameter(self.bias, self.b_step_size, opt)
            # print('meta_bn is computed')
        else:
            updated_weight = self.weight
            updated_bias = self.bias

        if opt == None:
            compute_each_batch = False
        else:
            try:
                if opt['each_domain']:
                    compute_each_batch = True
                else:
                    compute_each_batch = False
            except: # if opt['each_domain'] does not exist
                compute_each_batch = False
        if norm_type == "eval":
            compute_each_batch = False
        assert compute_each_batch == False 
        if compute_each_batch:
            domain_idx = opt['domains']
            unique_domain_idx = [int(x) for x in paddle.unique(domain_idx).cpu()]
            cnt = 0
            for j in unique_domain_idx:
                t_logical_domain = domain_idx == j

                if norm_type == "general":  # update, but not apply running_mean/var
                    result_local = F.batch_norm(inputs[t_logical_domain], self._mean, self._variance,
                                          updated_weight, updated_bias,
                                          self.training, self._momentum, self._epsilon)
                elif norm_type == "hold":  # not update, not apply running_mean/var
                    result_local = F.batch_norm(inputs[t_logical_domain], None, None,
                                          updated_weight, updated_bias,
                                          self.training, self._momentum, self._epsilon)
                elif norm_type == "eval":  # fix and apply running_mean/var,
                    if self._mean is None:
                        #result_local = F.batch_norm(inputs[t_logical_domain], None, None,
                        result_local = F.batch_norm(inputs[t_logical_domain], None, None,
                                              updated_weight, updated_bias,
                                              True, self._momentum, self._epsilon)
                    else:
                        result_local = F.batch_norm(inputs[t_logical_domain], self._mean, self._variance,
                                              updated_weight, updated_bias,
                                              False, self._momentum, self._epsilon)

                if cnt == 0:
                    result = copy.copy(result_local)
                else:
                    result = paddle.concat((result, result_local), 0)
                cnt += 1

        else:
            if norm_type == "general": # update, but not apply running_mean/var
                result = F.batch_norm(inputs, self._mean, self._variance,
                                      updated_weight, updated_bias,
                                      self.training, self._momentum, self._epsilon)
            elif norm_type == "hold": # not update, not apply running_mean/var
                #result = F.batch_norm(inputs, None, None,
                result = F.batch_norm(inputs, paddle.mean(inputs, axis=(0, 2, 3)), paddle.var(inputs, axis=(0, 2, 3)),
                                      updated_weight, updated_bias,
                                      self.training, self._momentum, self._epsilon)
            elif norm_type == "eval": # fix and apply running_mean/var,
                if self._mean is None:
                    #result = F.batch_norm(inputs, None, None,
                    result = F.batch_norm(inputs, paddle.mean(inputs, axis=(0, 2, 3)), paddle.var(inputs, axis=(0, 2, 3)),
                                          updated_weight, updated_bias,
                                          True, self._momentum, self._epsilon)
                else:
                    result = F.batch_norm(inputs, self._mean, self._variance,
                                          updated_weight, updated_bias,
                                          False, self._momentum, self._epsilon)
        return result

class meta_in(nn.InstanceNorm2D):
    def __init__(self, num_features, norm_opt, epsilon=1e-05, momentum=0.9, 
                weight_freeze = False, bias_freeze = False,
                data_format="NCHW", name=None):
        if not weight_freeze:
            weight_freeze = norm_opt['IN_W_FREEZE']
        if not bias_freeze:
            bias_freeze = norm_opt['IN_B_FREEZE']
        self.affine = False
        use_global_stats = norm_opt['IN_RUNNING']
        self._mean = None
        self._variance = None
        super().__init__(num_features, epsilon, momentum, None, None, data_format, name)
        self.in_fc_multiply = norm_opt['IN_FC_MULTIPLY']
        self._momentum = momentum


    def forward(self, inputs, opt = None):
        if inputs.dim() != 4:
            raise ValueError('expected 4D input (got {}D input)'.format(inputs.dim()))

        if (inputs.shape[2] == 1) and (inputs.shape[2] == 1): # fc layers
            inputs[:] *= self.in_fc_multiply
            return inputs
        else:
            if opt != None:
                use_meta_learning = False
                if opt['param_update']:
                    if self.scale is not None:
                        if self.compute_meta_params:
                            use_meta_learning = True
            else:
                use_meta_learning = False

            if self.training:
                norm_type = opt['type_running_stats']
            else:
                norm_type = "eval"

            if use_meta_learning and self.affine:
                # if opt['zero_grad']: self.zero_grad()
                updated_weight = update_parameter(self.scale, self.w_step_size, opt)
                updated_bias = update_parameter(self.bias, self.b_step_size, opt)
                # print('meta_bn is computed')
            else:
                updated_weight = self.scale
                updated_bias = self.bias


            if norm_type == "general":
                return F.instance_norm(inputs, self._mean, self._variance,
                                       updated_weight, updated_bias,
                                       self.training, self._momentum, self._epsilon)
            elif norm_type == "hold":
                return F.instance_norm(inputs, None, None,
                                       updated_weight, updated_bias,
                                       self.training, self._momentum, self._epsilon)
            elif norm_type == "eval":
                if self._mean is None:
                    return F.instance_norm(inputs, None, None,
                                           updated_weight, updated_bias,
                                           True, self._momentum, self._epsilon)
                else:
                    return F.instance_norm(inputs, self._mean, self._variance,
                                           updated_weight, updated_bias,
                                           False, self._momentum, self._epsilon)    
    