import os
from glob import glob

import numpy as np
import torch
import torch.backends.cudnn as cudnn
from torch.utils.tensorboard import SummaryWriter

from configurate import get_config
from dataloader import get_dataloader
from models.protonet import ProtoNet
from models.resnet import ResNet
from prototypical_loss import PrototypicalLoss
# from one_cycle_policy import OneCyclePolicy
from utils import AverageMeter

best_acc1 = 0
device = 'cuda' if torch.cuda.is_available() else 'cpu'
args = get_config()
writer = SummaryWriter(args.log_dir)


def main():
    global args, best_acc1, device

    # Init seed
    torch.cuda.cudnn_enabled = False
    np.random.seed(args.manual_seed)
    torch.manual_seed(args.manual_seed)
    torch.cuda.manual_seed(args.manual_seed)

    train_loader, val_loader = get_dataloader(args, args.dataset, 'train', 'val')

    input_dim = 1 if args.dataset == 'omniglot' else 3

    if args.model == 'protonet':
        model = ProtoNet(input_dim).to(device)
        print("ProtoNet loaded")
    else:
        model = ResNet(input_dim).to(device)
        print("ResNet loaded")

    criterion = PrototypicalLoss().to(device)

    optimizer = torch.optim.Adam(model.parameters(), args.lr)

    cudnn.benchmark = True

    if args.resume:
        checkpoint = torch.load(sorted(glob(f'{args.log_dir}/checkpoint_*.pth'), key=len)[-1])
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        start_epoch = checkpoint['epoch']
        best_acc1 = checkpoint['best_acc1']

        # scheduler = OneCyclePolicy(optimizer, args.lr, (args.epochs - start_epoch)*args.iterations)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer=optimizer,
                                                    gamma=args.lr_scheduler_gamma,
                                                    step_size=args.lr_scheduler_step)
        print(f"load checkpoint {args.exp_name}")
    else:
        start_epoch = 0
        # scheduler = OneCyclePolicy(optimizer, args.lr, args.epochs*args.iterations)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer=optimizer,
                                                    gamma=args.lr_scheduler_gamma,
                                                    step_size=args.lr_scheduler_step)

    print(f"model parameter : {sum(p.numel() for p in model.parameters() if p.requires_grad)}")

    for epoch in range(start_epoch, args.epochs):

        train_loss = train(train_loader, model, optimizer, criterion, epoch)
        val_loss, acc1 = validate(val_loader, model, criterion, epoch)

        if acc1 >= best_acc1:
            is_best = True
            best_acc1 = acc1
        else:
            is_best = False

        save_checkpoint({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'best_acc1': best_acc1,
            'optimizer_state_dict': optimizer.state_dict(),
        }, is_best)

        writer.add_scalar("Loss/1Epoch", val_loss, epoch)
        writer.add_scalar("Acc/1Epoch", acc1, epoch)

        print(f"[{epoch}/{args.epochs}] {train_loss:.3f}, {val_loss:.3f}, {acc1:.3f}, # {best_acc1:.3f}")

        scheduler.step()

    writer.close()


def train(train_loader, model, optimizer, criterion, epoch):
    losses = AverageMeter()
    num_support = args.num_support_tr
    total_epoch = len(train_loader) * epoch

    # switch to train mode
    model.train()
    for i, data in enumerate(train_loader):
        input, target = data[0].to(device), data[1].to(device)

        output = model(input)
        loss, acc1 = criterion(output, target, num_support)

        losses.update(loss.item(), input.size(0))

        # compute gradient and do optimize step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        writer.add_scalar("Loss/Train", loss.item(), total_epoch + i)
        writer.add_scalar("Acc/Train", acc1.item(), total_epoch + i)

    return losses.avg


@torch.no_grad()
def validate(val_loader, model, criterion, epoch):
    losses = AverageMeter()
    top1 = AverageMeter()
    num_support = args.num_support_val
    total_epoch = len(val_loader) * epoch

    # switch to evaluate mode
    model.eval()
    for i, data in enumerate(val_loader):
        input, target = data[0].to(device), data[1].to(device)

        output = model(input)
        loss, acc1 = criterion(output, target, num_support)

        losses.update(loss.item(), input.size(0))
        top1.update(acc1.item(), input.size(0))

        writer.add_scalar("Loss/Val", loss.item(), total_epoch + i)
        writer.add_scalar("Acc/Val", acc1.item(), total_epoch + i)

    return losses.avg, top1.avg


def save_checkpoint(state, is_best):
    directory = args.log_dir
    filename = directory + f"/checkpoint_{state['epoch']}.pth"

    if not os.path.exists(directory):
        os.makedirs(directory)

    torch.save(state, filename)

    if is_best:
        filename = directory + "/model_best.pth"
        torch.save(state, filename)


if __name__ == '__main__':
    main()
