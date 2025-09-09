import torch.nn as nn
import torch
from basemodel import BaseModel
from baseunit import TowerUnit

class Tarnet(BaseModel):
    def __init__(self, input_dim=100,discrete_size_cols=[2,3,4,5,2],embedding_dim=64,share_dim=6,
                 share_hidden_dims =[64,64,64,64,64],
                 base_hidden_dims=[100,100,100,100],output_activation_base=torch.nn.Sigmoid(),
                 share_hidden_func = torch.nn.ELU(),base_hidden_func = torch.nn.ELU(),
                 task = 'classification',classi_nums=2, treatment_label_list=[0,1,2,3],model_type='Tarnet',device='cpu'):
        super(Tarnet, self).__init__()
        self.model_type = model_type
        self.layers = []
        self.treatment_nums = len(treatment_label_list)
        self.treatment_model = nn.ModuleDict()
        self.treatment_label_list = treatment_label_list
        input_dim = input_dim - len(discrete_size_cols) + len(discrete_size_cols)*embedding_dim

        # embedding 
        self.embeddings = nn.ModuleList([
            nn.Embedding(size, embedding_dim).to(device) for size in discrete_size_cols
        ]).to(device)
        
        # share tower
        self.share_tower = TowerUnit(input_dim = input_dim, 
                 hidden_dims=share_hidden_dims, 
                 share_output_dim=share_dim, 
                 activation=share_hidden_func, 
                 use_batch_norm=True, 
                 use_dropout=True, 
                 dropout_rate=0.3, 
                 task='share', 
                 classi_nums=None, 
                 device=device, 
                 use_xavier=True)

        for treatment_label in self.treatment_label_list:
            # treatment tower
            self.treatment_model[str(treatment_label)] = TowerUnit(input_dim = share_dim, 
                 hidden_dims=base_hidden_dims, 
                 share_output_dim=None, 
                 activation=base_hidden_func, 
                 use_batch_norm=True, 
                 use_dropout=True, 
                 dropout_rate=0.3, 
                 task=task, 
                 classi_nums=classi_nums, 
                 output_activation=output_activation_base,
                 device=device, 
                 use_xavier=True)
    
    def forward(self, X, t, X_discrete=None, X_continuous=None):
        embedded = [emb(X_discrete[:, i].long()) for i, emb in enumerate(self.embeddings)]
        X_discrete_emb = torch.cat(embedded, dim=1)  # 拼接所有embedding
        x = torch.cat((X_continuous,X_discrete_emb), dim=1)

        share_out = self.share_tower(x)

        pre = []
        ate = []

        for treatment_label in self.treatment_label_list:
            predcit_pro = self.treatment_model[str(treatment_label)](share_out).squeeze().unsqueeze(1)
            pre.append(predcit_pro)

        if not self.training:
            base_predcit_pro = self.treatment_model['0'](share_out).squeeze().unsqueeze(1)
            for treatment_label in self.treatment_label_list:
                predcit_pro = self.treatment_model[str(treatment_label)](share_out).squeeze().unsqueeze(1)
                if treatment_label != 0:
                    ate.append(predcit_pro -base_predcit_pro)
        return torch.cat(ate, dim=1) if len(ate) !=0 else None,pre,share_out

def gaussian_kernel(x, y, sigma=1.0):
    """
    计算RBF核矩阵
    x: [n, d]
    y: [m, d]
    """
    x = x.unsqueeze(1)  # [n, 1, d]
    y = y.unsqueeze(0)  # [1, m, d]
    diff = x - y        # [n, m, d]
    dist_sq = (diff ** 2).sum(-1)  # [n, m]
    return torch.exp(-dist_sq / (2 * sigma ** 2))

def mmd_rbf(x, y, sigma=1.0):
    """
    计算两个样本集合x和y的MMD^2（RBF核）
    x: [n, d]
    y: [m, d]
    """
    K_xx = gaussian_kernel(x, x, sigma)
    K_yy = gaussian_kernel(y, y, sigma)
    K_xy = gaussian_kernel(x, y, sigma)
    mmd = K_xx.mean() + K_yy.mean() - 2 * K_xy.mean()
    return mmd

def cfrnet_loss(y_preds,t, y_true,task='regression',loss_type=None,classi_nums=2, treatment_label_list=None,X_true=None):
    if task is None:
        raise ValueError("task must be 'classification' or 'regression'")

    t = t.squeeze().unsqueeze(1).long()
    y_true = y_true.squeeze().unsqueeze(1)
    y_pred = torch.gather(torch.cat(y_preds, dim=1), dim=1, index=t.long()).squeeze().unsqueeze(1)

    y_true_dict = {}
    y_pred_dict = {}
    x_true_dict = {}
    for treatment in treatment_label_list:
        mask = (t == treatment)
        y_true_dict[treatment] = y_true[mask]
        y_pred_dict[treatment] = y_pred[mask]
        x_true_dict[treatment] = X_true[mask]
        
    # 计算每个treatment的损失
    if task == 'classification':
        if loss_type == 'BCEWithLogitsLoss':
            criterion = nn.BCEWithLogitsLoss()
        elif loss_type =='BCELoss':
            criterion = nn.BCELoss()
        else:
            raise ValueError("loss_type must be 'BCEWithLogitsLoss' or 'BCELoss'")
    elif task == 'regression':
        if loss_type == 'mse':
            criterion = nn.MSELoss()
        elif loss_type =='huberloss':
            criterion = nn.SmoothL1Loss() 
        else:
            raise ValueError("loss_type must be 'mse' or 'huberloss'")
    else:
        raise ValueError("task must be 'classification' or'regression'")
    
    loss_treat = 0
    for treatment in treatment_label_list:
        loss_treat += criterion(y_pred_dict[treatment], y_true_dict[treatment])

    loss_mmd = 0
    for treatment in treatment_label_list:
        if treatment!= 0:
            loss_mmd += mmd_rbf(x_true_dict[treatment], x_true_dict[0])

    loss = loss_treat + loss_mmd
    return loss, loss_treat, None



        
        