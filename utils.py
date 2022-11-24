import os
import math
from PIL.Image import Image
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.distributions.bernoulli import Bernoulli
from operator import itemgetter

from build_vocab import PAD_TOKEN, UNK_TOKEN

#----------------------------
# defines
#----------------------------
_cX = 0
_cY = 1
_x = 2
_y = 3
_w = 4
_h = 5

#----------------------------
# HyperParameters
#----------------------------
num_dirs = 8
threshold = 1000 # downscale the input image to have atmost <threshold> number of pixels in its larger dimension

def process(img):
    '''
    import the image and convert it to the required size determined by the hyperparameter threshold
    Also, return the downscaled and grayscaled image
    '''
    if img.shape[0] > img.shape[1]:
        ratio = threshold/img.shape[0]
    

    img = cv2.resize(src = img, dsize = (0,0), fx = ratio, fy = ratio)
    #orig_img = img.copy()

    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    #gray_img = 255*(gray_img < 80).astype(np.uint8)
    
    #----------------------------------------------------------#
    # If you want this to work, you will have to invt the image#
    #----------------------------------------------------------#

    #coords = cv2.findNonZero(gray_img)
    #x, y, w, h = cv2.boundingRect(coords)
    #img = img[y:y+h,x:x+w]
    #gray_img = gray_img[y:y+h,x:x+w]
    
    return img, gray_img


def symSeg(img, printOP = False):
    '''
    
    '''
    img, gray_img = process(img)
    thresh = cv2.threshold(gray_img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    im_data = cv2.connectedComponentsWithStats(thresh, cv2.CV_32S, 4)
    (numLabels, labels, stats, centroids) = im_data

    # filtering noise points by checking area
    # Actually I cannot do this, otherwise we cannot identify 'therefore' symbol
    '''
    temp_s = []
    temp_c = []
    for i in range(len(stats)):
        if stats[i, cv2.CC_STAT_AREA] > 40:
            temp_s.append(stats[i])
            temp_c.append(centroids[i])
    stats = temp_s
    centroids = temp_c
    '''
    #for i in range(len(stats)):
    #    print(stats[i])
    
    coordinates = []
    for i in range(len(stats)):
        #print(stats[i])
        x = stats[i][cv2.CC_STAT_LEFT]
        y = stats[i][cv2.CC_STAT_TOP]
        w = stats[i][cv2.CC_STAT_WIDTH]
        h = stats[i][cv2.CC_STAT_HEIGHT]
        (cX, cY) = centroids[i]
        coordinates.append([cX, cY, x ,y , w, h])
    #sorted(coordinates, key=itemgetter(0,1))
    #sorted(coordinates, key=itemgetter(0,1))
    
    coordinates.pop(0) # remove the default bounding box
    #for i in range(len(coordinates)):
    #    print(coordinates[i])

    coordinates = sorted(coordinates, key = itemgetter(_cX, _cY))
    
    #for i in range(len(coordinates)):
    #    print(coordinates[i])

    if printOP == True:
        for i in range(len(coordinates)):
            #x = stats[i, cv2.CC_STAT_LEFT]
            #y = stats[i, cv2.CC_STAT_TOP]
            #w = stats[i, cv2.CC_STAT_WIDTH]
            #h = stats[i, cv2.CC_STAT_HEIGHT]
            #(cX, cY) = centroids[i]
            x,y = coordinates[i][_x], coordinates[i][_y]
            w,h = coordinates[i][_w], coordinates[i][_h]
            img = cv2.rectangle(img, (x,y), (x+w, y+h), (0, 255, 0), 3)
            cX,cY = coordinates[i][_cX], coordinates[i][_cY]
            img = cv2.circle(img, (int(cX), int(cY)), 4, (0,0,255), -1)
            img = cv2.putText(img, str(i), (int(cX), int(cY)), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=0.5, color=(0, 0, 0),thickness=1)
            #print(i, "X: ", cX, "Y: ", cY)
        
        cv2.imshow("gray", thresh)
        cv2.waitKey(0)
        #cv2.imshow("Input Image", orig_img)
        cv2.imshow("Bounding Boxes", img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    
    #cv2.imwrite('thresh.jpg', thresh)
    #cv2.imwrite('BoundingBoxes.jpg', img)

    return (coordinates, thresh)


def graphBuilder(coordinates, img):
    #Note: This implementation does not guarantee an undirected graph.
    edges = []
    num_nodes = len(coordinates)
    for i in range(num_nodes):
        for j in range(max(i-10, 0), min(i+10, num_nodes)):
            _,_,xj,yj,_,_ = coordinates[j]
            point = xj,yj
            if isInside(point, coordinates[i], img.shape):
                edges.append([i,j])
    edges = np.array(edges).T
    return edges


def isInside(point, coordinates, img_dims):
    deltaX = int(img_dims[0]*0.3)
    deltaY = int(img_dims[1]*0.3)
    cX, cY, xi, yi, wi, hi = coordinates
    xmax = cX + deltaX
    xmin = cX - deltaX
    ymax = cY + deltaY
    ymin = cY - deltaY
    if point[0] < xmax and point[0] > xmin and point[1] < ymax and point[1] > ymin:
        return True
    return False


def collate_fn(sign2id, batch):
    # filter the pictures that have different weight or height
    size = batch[0][0].size()
    batch = [img_formula for img_formula in batch
             if img_formula[0].size() == size]
    # sort by the length of formula
    batch.sort(key=lambda img_formula: len(img_formula[1].split()),
               reverse=True)

    imgs, formulas = zip(*batch)
    formulas = [formula.split() for formula in formulas]
    # targets for training , begin with START_TOKEN
    tgt4training = formulas2tensor(add_start_token(formulas), sign2id)
    # targets for calculating loss , end with END_TOKEN
    tgt4cal_loss = formulas2tensor(add_end_token(formulas), sign2id)
    imgs = torch.stack(imgs, dim=0)
    return imgs, tgt4training, tgt4cal_loss


def formulas2tensor(formulas, sign2id):
    """convert formula to tensor"""

    batch_size = len(formulas)
    max_len = len(formulas[0])
    tensors = torch.ones(batch_size, max_len, dtype=torch.long) * PAD_TOKEN
    for i, formula in enumerate(formulas):
        for j, sign in enumerate(formula):
            tensors[i][j] = sign2id.get(sign, UNK_TOKEN)
    return tensors


def add_start_token(formulas):
    return [['<s>']+formula for formula in formulas]


def add_end_token(formulas):
    return [formula+['</s>'] for formula in formulas]


def count_parameters(model):
    """count model parameters"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def tile(x, count, dim=0):
    """
    Tiles x on dimension dim count times.
    """
    perm = list(range(len(x.size())))
    if dim != 0:
        perm[0], perm[dim] = perm[dim], perm[0]
        x = x.permute(perm).contiguous()
    out_size = list(x.size())
    out_size[0] *= count
    batch = x.size(0)
    x = x.view(batch, -1) \
         .transpose(0, 1) \
         .repeat(count, 1) \
         .transpose(0, 1) \
         .contiguous() \
         .view(*out_size)
    if dim != 0:
        x = x.permute(perm).contiguous()
    return x


def load_formulas(filename):
    formulas = dict()
    with open(filename) as f:
        for idx, line in enumerate(f):
            formulas[idx] = line.strip()
    print("Loaded {} formulas from {}".format(len(formulas), filename))
    return formulas


def cal_loss(logits, targets):
    """args:
        logits: probability distribution return by model
                [B, MAX_LEN, voc_size]
        targets: target formulas
                [B, MAX_LEN]
    """
    padding = torch.ones_like(targets) * PAD_TOKEN
    mask = (targets != padding)

    targets = targets.masked_select(mask)
    logits = logits.masked_select(
        mask.unsqueeze(2).expand(-1, -1, logits.size(2))
    ).contiguous().view(-1, logits.size(2))
    logits = torch.log(logits)

    assert logits.size(0) == targets.size(0)

    loss = F.nll_loss(logits, targets)
    return loss


def get_checkpoint(ckpt_dir):
    """return full path if there is ckpt in ckpt_dir else None"""
    if not os.path.isdir(ckpt_dir):
        raise FileNotFoundError("No checkpoint found in {}".format(ckpt_dir))

    ckpts = [f for f in os.listdir(ckpt_dir) if f.startswith('ckpt')]
    if not ckpts:
        raise FileNotFoundError("No checkpoint found in {}".format(ckpt_dir))

    last_ckpt, max_epoch = None, 0
    for ckpt in ckpts:
        epoch = int(ckpt.split('-')[1])
        if epoch > max_epoch:
            max_epoch = epoch
            last_ckpt = ckpt
    full_path = os.path.join(ckpt_dir, last_ckpt)
    print("Get checkpoint from {} for training".format(full_path))
    return full_path


def schedule_sample(prev_logit, prev_tgt, epsilon):
    prev_out = torch.argmax(prev_logit, dim=1, keepdim=True)
    prev_choices = torch.cat([prev_out, prev_tgt], dim=1)  # [B, 2]
    batch_size = prev_choices.size(0)
    prob = Bernoulli(torch.tensor([epsilon]*batch_size).unsqueeze(1))
    # sampling
    sample = prob.sample().long().to(prev_tgt.device)
    next_inp = torch.gather(prev_choices, 1, sample)
    return next_inp


def cal_epsilon(k, step, method):
    """
    Reference:
        Scheduled Sampling for Sequence Prediction with Recurrent Neural Networks
        See details in https://arxiv.org/pdf/1506.03099.pdf
    """
    assert method in ['inv_sigmoid', 'exp', 'teacher_forcing']

    if method == 'exp':
        return k**step
    elif method == 'inv_sigmoid':
        return k/(k+math.exp(step/k))
    else:
        return 1.

        
def extract_inputs_from_image(img: Image):
    """
    Input:
    - img: 3 channel PNG image for formula.
           type: PIL.Image.Image
    Output: a tuple of the following three items
    - coordinates: numpy array of shape [4, L], where L is the number of
      symbols.
    - symbols: np.ndarray of shape [L, 1, 32, 32], where L is the number of
      symbols.
    - edge_indices: np.ndarray of shape [2, 2E], where E is number of edges in
      a graph. Note that we have 2E in the shape because graph is undirected.

    All the necessary normalizing and reshaping (if any) must be done here
    itself.
    """
    # @Ninad
    # TODO: Add/modify the code in any way to get the appropriate output

    (coords,thresh) = symSeg(img, printOP = False)
    edge_indices = graphBuilder(coords, thresh)

    #LOSViewer(coordinates, edges)
    '''
    for i in range(len(data[0])):
        print(data[0,i], data[1,i])
    '''
    

    #---------------------------------------------------------#
    #                Generating output variables              #
    #---------------------------------------------------------#


    ret_cor = []    # Variable that return 4xL coordinates
    ret_sym = []    # Variable that returns Lx1x32x32 images
    max_dim = 0
    for i in range(len(coords)):
        cX, cY, x, y, w, h = coords[i]
        ret_cor.append([cX, cY, h, w])
        if w > max_dim:
            idx = i
            max_dim = w
        if h > max_dim:
            idx = i
            max_dim = h
    #print(max_dim)
    ret_cor = np.array(ret_cor).T
    ratio = 32/max_dim

    cX, cY, x, y, w, h = coords[idx]

    '''
    tmp = thresh[y:y+h, x:x+w]

    cv2.imshow('',tmp)
    cv2.waitKey(0)
    '''

    for i in range(len(coords)):
        cX, cY, x, y, w, h = coords[i]
        tmp_sym = thresh[y:y+h, x:x+w]
        #TODO: initialize a 32x32 matrix and superimpose
        tmp_sym = cv2.resize(src = tmp_sym, dsize = (0,0), fx = ratio, fy = ratio)
        tmp_sym = np.pad(tmp_sym, [(0,32-tmp_sym.shape[0]),(0,32-tmp_sym.shape[1])])
        #pdb.set_trace()
        tmp_sym = tmp_sym[None, ...]
        #print(i, ':', tmp_sym.shape)
        ret_sym.append(tmp_sym)
    ret_sym = np.array(ret_sym)
    
    
    
    
    
    #print(ret_cor.shape)
    #print(ret_sym.shape)
    #print(edges.shape)
    
    
    #print(ret_cor.shape)
    #print(ret_sym.shape)
    #print(edges.shape)

    
    #print(ret_cor.shape)
    #print(ret_sym.shape)
    #print(edge_indices.shape)

    return (coords, ret_sym, edge_indices)
