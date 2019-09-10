#AUTOGENERATED! DO NOT EDIT! File to edit: dev/18_callback_fp16.ipynb (unless otherwise specified).

__all__ = ['get_master', 'to_master_grads', 'to_model_params', 'test_overflow', 'grad_overflow', 'MixedPrecision']

#Cell
from ..torch_basics import *
from ..test import *
from ..layers import *
from ..data.all import *
from ..notebook.showdoc import show_doc
from ..optimizer import *
from ..learner import *
from .progress import *

#Cell
from ..utils.fp16_utils import convert_network, model_grads_to_master_grads, master_params_to_model_params

#Cell
from torch.nn.utils import parameters_to_vector

def get_master(opt, flat_master=False):
    model_params = [[param for param in pg if param.requires_grad] for pg in opt.param_groups]
    if flat_master:
        master_params = []
        for pg in model_params:
            mp = parameters_to_vector([param.data.float() for param in pg])
            mp = torch.nn.Parameter(mp, requires_grad=True)
            if mp.grad is None: mp.grad = mp.new(*mp.size())
            master_params.append([mp])
    else:
        master_params = [[param.clone().float().detach() for param in pg] for pg in model_params]
        for pg in master_params:
            for param in pg: param.requires_grad_(True)
    return model_params, master_params

#Cell
def to_master_grads(model_pgs, master_pgs, flat_master=False):
    for (model_params,master_params) in zip(model_pgs,master_pgs):
        model_grads_to_master_grads(model_params, master_params, flat_master=flat_master)

#Cell
def to_model_params(model_pgs, master_pgs, flat_master:bool=False)->None:
    for (model_params,master_params) in zip(model_pgs,master_pgs):
        master_params_to_model_params(model_params, master_params, flat_master=flat_master)

#Cell
def test_overflow(x):
    s = float(x.float().sum())
    return (s == float('inf') or s == float('-inf') or s != s)

#Cell
def grad_overflow(pgs):
    for pg in pgs:
        for p in pg:
            if p.grad is not None and test_overflow(p.grad.data): return True
    return False

#Cell
@docs
class MixedPrecision(Callback):
    "Run training in mixed precision"
    toward_end=True

    def __init__(self, loss_scale=512, flat_master=False, dynamic=True, max_loss_scale=2.**24,
                 div_factor=2., scale_wait=500, clip=None):
        assert torch.backends.cudnn.enabled, "Mixed precision training requires cudnn."
        self.flat_master,self.dynamic,self.max_loss_scale = flat_master,dynamic,max_loss_scale
        self.div_factor,self.scale_wait,self.clip = div_factor,scale_wait,clip
        self.loss_scale = max_loss_scale if dynamic else loss_scale

    def begin_fit(self):
        self.learn.model = convert_network(self.model, dtype=torch.float16)
        self.model_pgs,self.master_pgs = get_master(self.opt, self.flat_master)
        #Changes the optimizer so that the optimization step is done in FP32.
        self.learn.opt.param_groups = self.master_pgs
        if self.dynamic: self.count = 0

    def begin_batch(self):
        if self.xb.dtype not in [torch.int16, torch.int32, torch.int64]: self.learn.xb = self.xb.half()

    def after_pred(self):  self.learn.pred = self.pred.float()
    def after_loss(self):
        if self.training: self.learn.loss *= self.loss_scale

    def after_backward(self):
        self.learn.loss /= self.loss_scale #To record the real loss
        #First, check for an overflow
        if self.dynamic and grad_overflow(self.model_pgs):
            self.loss_scale /= self.div_factor
            self.model.zero_grad()
            raise CancelBatchException() #skip step and zero_grad

        to_master_grads(self.model_pgs, self.master_pgs, self.flat_master)
        for master_params in self.master_pgs:
            for param in master_params:
                if param.grad is not None: param.grad.div_(self.loss_scale)
        #Check if it's been long enough without overflow
        if self.clip is not None:
            for group in self.master_pgs: nn.utils.clip_grad_norm_(group, self.clip)
        if self.dynamic:
            self.count += 1
            if self.count == self.scale_wait:
                self.count = 0
                self.loss_scale *= self.div_factor

    def after_step(self):
        self.model.zero_grad() #Zero the gradients of the model manually (optimizer disconnected)
        to_model_params(self.model_pgs, self.master_pgs, self.flat_master)

    def after_fit(self):
        self.learn.model = convert_network(self.model, dtype=torch.float32)

    _docs = dict(begin_fit="Put the model in FP16 and prepare the two copies of the parameters",
                 begin_batch="Put the input in FP16",
                 after_pred="Put the output back to FP32 so that the loss is computed in FP32",
                 after_loss="Apply loss scaling to avoid gradient underflow",
                 after_backward="Copy the gradients to the master param and undo the loss scaling",
                 after_step="Copy the master params to the model params",
                 after_fit="Put the model back in FP32"
    )