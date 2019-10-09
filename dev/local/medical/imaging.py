#AUTOGENERATED! DO NOT EDIT! File to edit: dev/60_medical_imaging.ipynb (unless otherwise specified).

__all__ = ['DcmDataset', 'DcmTag', 'DcmMultiValue', 'dcmread', 'pixels', 'scaled_px', 'array_freqhist_bins',
           'dicom_windows', 'show']

#Cell
from ..torch_basics import *
from ..test import *
from ..core import *
from ..layers import *
from ..data.all import *
from ..optimizer import *
from ..learner import *
from ..metrics import *
from ..vision import models

import pydicom
from pydicom.dataset import Dataset as DcmDataset
from pydicom.tag import BaseTag as DcmTag
from pydicom.multival import MultiValue as DcmMultiValue

from scipy import ndimage
import skimage

#Cell
@patch
def dcmread(self:Path): return pydicom.dcmread(str(self))

#Cell
@patch_property
def pixels(self:DcmDataset):
    "`pixel_array` as a tensor"
    return tensor(self.pixel_array.astype(np.float32))

#Cell
@patch_property
def scaled_px(self:DcmDataset):
    "`pixels` scaled by `RescaleSlope` and `RescaleIntercept"
    img = self.pixels
    return img*self.RescaleSlope + self.RescaleIntercept

#Cell
def array_freqhist_bins(self, n_bins=100):
    imsd = np.sort(self.flatten())
    t = np.array([0.001])
    t = np.append(t, np.arange(n_bins)/n_bins+(1/2/n_bins))
    t = np.append(t, 0.999)
    t = (len(imsd)*t+0.5).astype(np.int)
    return np.unique(imsd[t])

#Cell
@patch
def freqhist_bins(self:Tensor, n_bins=100):
    imsd = self.view(-1).sort()[0]
    t = torch.cat([tensor([0.001]),
                   torch.arange(n_bins).float()/n_bins+(1/2/n_bins),
                   tensor([0.999])])
    t = (len(imsd)*t).long()
    return imsd[t].unique()

#Cell
@patch
def hist_scaled(self:Tensor, brks=None):
    if brks is None: brks = self.freqhist_bins()
    ys = torch.arange(len(brks), dtype=torch.float) / brks[-1]
    return self.flatten().interp_1d(brks, ys).reshape(self.shape)

#Cell
@patch
def hist_scaled_px(self:DcmDataset, brks=None, min_px=None, max_px=None):
    px = self.scaled_px
    if min_px is not None: px[px<min_px] = min_px
    if max_px is not None: px[px>max_px] = max_px
    return px.hist_scaled()

#Cell
@patch
def windowed(self:DcmDataset, w, l):
    px = self.scaled_px.float()
    px_min = l - w//2
    px_max = l + w//2
    px[px<px_min] = px_min
    px[px>px_max] = px_max
    return (px-px_min) / (px_max-px_min)

#Cell
# From https://radiopaedia.org/articles/windowing-ct
dicom_windows = types.SimpleNamespace(
    brain=(80,40),
    subdural=(200,80),
    stroke=(8,32),
    brain_bone=(2800,600),
    brain_soft=(375,40),
    lungs=(1500,-600),
    mediastinum=(350,50),
    abdomen_soft=(400,50),
    liver=(150,30),
    spine_soft=(250,50),
    spine_bone=(1800,400)
)

#Cell
@patch
@delegates(show_image)
def show(self:DcmDataset, scale=True, cmap=plt.cm.bone, min_px=-1000, max_px=None, **kwargs):
    px = (self.windowed(*scale) if isinstance(scale,tuple)
          else self.hist_scaled_px(min_px=min_px,max_px=max_px) if scale
          else self.scaled_px)
    show_image(px, cmap=cmap, **kwargs)

#Cell
@patch
def zoom(self:DcmDataset, ratio):
    data_d = ndimage.zoom(self.pixel_array, ratio)
    self.PixelData = data_d.tobytes()
    self.Rows,self.Columns = data_d.shape

#Cell
def _cast_dicom_special(x):
    cls = type(x)
    if not cls.__module__.startswith('pydicom'): return x
    return cls.__base__(x)

def _split_elem(res,k,v):
    if not isinstance(v,DcmMultiValue): return
    res[f'Multi{k}'] = 1
    for i,o in enumerate(v): res[f'{k}{"" if i==0 else i}']=o

#Cell
@patch
def as_dict(self:DcmDataset, px_summ=True):
    pxdata = (0x7fe0,0x0010)
    vals = [self[o] for o in self.keys() if o != pxdata]
    its = [(v.keyword,v.value) for v in vals]
    res = dict(its)
    res['fname'] = self.filename
    for k,v in its: _split_elem(res,k,v)
    if not px_summ: return res
    stats = 'min','max','mean','std'
    try:
        pxs = self.pixel_array
        for f in stats: res['img_'+f] = getattr(pxs,f)()
    except Exception as e:
        for f in stats: res['img_'+f] = 0
        print(res,e)
    for k in res: res[k] = _cast_dicom_special(res[k])
    return res

#Cell
def _dcm2dict(px_summ, fn): return fn.dcmread().as_dict(px_summ)

#Cell
@delegates(parallel)
def _from_dicoms(cls, fns, px_summ=True, **kwargs): return pd.DataFrame(parallel(partial(_dcm2dict,px_summ), fns, **kwargs))
pd.DataFrame.from_dicoms = classmethod(_from_dicoms)