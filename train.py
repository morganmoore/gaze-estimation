import torch
from datasets.unity_eyes import UnityEyesDataset
from torch.utils.data import DataLoader
from models.posenet import PoseNet
import os
from torch.utils.tensorboard import SummaryWriter
from datetime import datetime
import numpy as np
import cv2

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(device)

# default `log_dir` is "runs" - we'll be more specific here
timestr = datetime.now().strftime("%m-%d-Y-%H-%M-%S")
writer = SummaryWriter(f'runs/posenet{timestr}')

dataset = UnityEyesDataset()
N = len(dataset)

VN = 100
TN = N - VN
train_set, val_set = torch.utils.data.random_split(dataset, (TN, VN))

dataloader = DataLoader(train_set, batch_size=4,
                        shuffle=True, num_workers=8)
valDataLoader = DataLoader(val_set, batch_size=4,
                        shuffle=True, num_workers=8)

posenet = PoseNet(nstack=8, inp_dim=256, oup_dim=18)
posenet.to(device)

# Use the optim package to define an Optimizer that will update the weights of
# the model for us. Here we will use Adam; the optim package contains many other
# optimization algoriths. The first argument to the Adam constructor tells the
# optimizer which Tensors it should update.
learning_rate = 1e-4
optimizer = torch.optim.Adam(posenet.parameters(), lr=learning_rate)


if os.path.exists('checkpoint'):
    checkpoint = torch.load('checkpoint')
    posenet.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

for i_batch, sample_batched in enumerate(dataloader):
    if i_batch % 20 == 0:
        torch.save({
            'model_state_dict': posenet.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
        }, 'checkpoint')

    print(i_batch, sample_batched['img'].size(),
          len(sample_batched['heatmaps']))

    X = torch.tensor(sample_batched['img'], dtype=torch.float32).to(device)
    heatmaps_pred, landmarks_pred = posenet.forward(X)

    heatmaps = sample_batched['heatmaps']
    landmarks = torch.tensor(sample_batched['landmarks'], dtype=torch.float32)

    heatmaps_loss, landmarks_loss = posenet.calc_loss(heatmaps_pred, heatmaps, landmarks_pred, landmarks)

    loss = 1000 * heatmaps_loss + landmarks_loss

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    hm = np.mean(heatmaps[-1, 8:16].detach().numpy(), axis=0)
    hm_pred = np.mean(heatmaps_pred[-1, -1, 8:16].detach().numpy(), axis=0)
    norm_hm = cv2.normalize(hm, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)
    norm_hm_pred = cv2.normalize(hm_pred, None, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F)

    cv2.imwrite('true.jpg', norm_hm * 255)
    cv2.imwrite('pred.jpg', norm_hm_pred * 255)
    cv2.imwrite('eye.jpg', sample_batched['img'].numpy()[-1] * 255)

    writer.add_scalar("Training heatmaps loss", heatmaps_loss.item(), i_batch)
    writer.add_scalar("Training landmarks loss", landmarks_loss.item(), i_batch)
    writer.add_scalar("Training loss", loss.item(), i_batch)

    if i_batch % 20 == 0:
        with torch.no_grad():
            val_losses = []
            for val_batch in valDataLoader:
                X = torch.tensor(val_batch['img'], dtype=torch.float32)
                landmarks = val_batch['heatmaps']
                landmarks = val_batch['landmarks']
                heatmaps_pred, landmarks_pred = posenet.forward(X)
                heatmaps_loss, landmarks_loss = posenet.calc_loss(heatmaps_pred, heatmaps, landmarks_pred, landmarks)
                loss = 1000 * heatmaps_loss + landmarks_loss
                val_losses.append(loss.item())
            val_loss = np.mean(val_losses)
            writer.add_scalar("validation loss", 1000 * val_loss, i_batch)
        print(i_batch, 'validation loss', val_loss)


