# -*- coding: utf-8 -*-
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import argparse
import json

import torch
import torch.nn.functional as F
from torch.utils.tensorboard.writer import SummaryWriter

from ignite.engine import Events, Engine
from ignite.metrics import Accuracy, Average, Loss
from ignite.contrib.handlers import ProgressBar
from ignite.handlers import EarlyStopping
from ignite.handlers import Checkpoint, global_step_from_engine

from gpytorch.mlls import VariationalELBO
from gpytorch.likelihoods import SoftmaxLikelihood

from due import dkl_Phison_mo, dkl_Phison_mo_s2
# from due.wide_resnet_Phison import WideResNet
from due.sngp import Laplace

from lib.datasets_mo import get_dataset
from lib.evaluate_ood_Phison import get_ood_metrics
from lib.utils import get_results_directory, Hyperparameters, set_seed
from pytorch_metric_learning import samplers

import os



torch.backends.cudnn.benchmark = True

def set_gpmodel(hparams, train_com_loader, train_com_dataset, num_classes):
    
    if hparams.coeff ==1 :
        from networks.mobilenetv3_HybridExpert import SupConMobileNetV3Large
    elif hparams.coeff ==3 :
        from networks.mobilenetv3_SN3 import SupConMobileNetV3Large
    elif hparams.coeff ==5 :
        from networks.mobilenetv3_SN5 import SupConMobileNetV3Large
    elif hparams.coeff ==7 :
        from networks.mobilenetv3_SN7 import SupConMobileNetV3Large
    elif hparams.coeff ==0 :
        from networks.mobilenetv3 import SupConMobileNetV3Large
    
    # stage 1
    feature_extractor = SupConMobileNetV3Large()
    
    initial_inducing_points, initial_lengthscale = dkl_Phison_mo.initial_values(
        train_com_loader, feature_extractor, hparams.n_inducing_points # if hparams.n_inducing_points= none ,hparams.n_inducing_points = num_class
    )

    gp = dkl_Phison_mo.GP(
        num_outputs=num_classes, #可能=conponent 數量 = 23個 
        initial_lengthscale=initial_lengthscale,
        initial_inducing_points=initial_inducing_points,
        kernel=hparams.kernel,
    )

    gpmodel_s1 = dkl_Phison_mo.DKL(feature_extractor, gp)

    likelihood = SoftmaxLikelihood(num_classes=num_classes, mixing_weights=False)
    likelihood = likelihood.cuda()

    elbo_fn = VariationalELBO(likelihood, gp, num_data=len(train_com_dataset))
    loss_fn = lambda x, y: -elbo_fn(x, y)
    
    ckpt = torch.load(hparams.checkpoint_path, map_location='cpu')

#     for k, v in ckpt.items():  # k 参数名 v 对应参数值
#         print(k)
#     import pdb;pdb.set_trace()

#     if torch.cuda.is_available():
    gpmodel_s1 = gpmodel_s1.cuda()
    likelihood = likelihood.cuda()
#         cudnn.benchmark = True
    gpmodel_s1.load_state_dict(ckpt)
    
#     import pdb;pdb.set_trace()
#         # stage 2 
    feature_extractor_s1 = gpmodel_s1.feature_extractor
    feature_extractor_s1.eval()
    
    initial_inducing_points, initial_lengthscale = dkl_Phison_mo_s2.initial_values(
        train_com_loader, feature_extractor_s1, hparams.n_inducing_points*50 # if hparams.n_inducing_points= none ,hparams.n_inducing_points = num_class
    )
    
    print('initial_inducing_points : ', initial_inducing_points.shape)
    gp = dkl_Phison_mo_s2.GP(
        num_outputs=num_classes, #可能=conponent 數量 = 23個 
        initial_lengthscale=initial_lengthscale,
        initial_inducing_points=initial_inducing_points,
        kernel=hparams.kernel,
    )

    gpmodel = dkl_Phison_mo_s2.DKL(gp)
    gpmodel = gpmodel.cuda()

    likelihood = SoftmaxLikelihood(num_classes=num_classes, mixing_weights=False)
    likelihood = likelihood.cuda()

    elbo_fn = VariationalELBO(likelihood, gp, num_data=len(train_com_dataset))
    loss_fn = lambda x, y: -elbo_fn(x, y)
    
    return feature_extractor_s1, gpmodel, likelihood, loss_fn

def main(hparams):
    results_dir = get_results_directory(hparams.output_dir)
    writer = SummaryWriter(log_dir=str(results_dir))
    
    hparams.seed = set_seed(hparams.seed)

    ds = get_dataset(hparams.dataset,hparams.seed, root=hparams.data_root)
#     input_size, num_classes, train_dataset, test_dataset, train_loader, train_com_loader = ds

    input_size ,num_classes , train_com_loader, train_loader, test_dataset ,train_cls_dataset,train_com_dataset, test_com_dataset = ds
    
    

    if hparams.n_inducing_points is None:
        hparams.n_inducing_points = num_classes
        
#     if hparams.n_inducing_points_cls is None:
#         hparams.n_inducing_points_cls = 20

    print(f"Training with {hparams}")
    hparams.save(results_dir / "hparams.json")
    
    global best_loss
    best_loss =100

#     model, loss_fn_cls = set_model(hparams)
    
#     # stage 1 
#     initial_inducing_points, initial_lengthscale = dkl_Phison_mo.initial_values(
#         train_com_loader, model, hparams.n_inducing_points # if hparams.n_inducing_points= none ,hparams.n_inducing_points = num_class
#     )

#     gp = dkl_Phison_mo.GP(
#         num_outputs=num_classes, #可能=conponent 數量 = 23個 
#         initial_lengthscale=initial_lengthscale,
#         initial_inducing_points=initial_inducing_points,
#         kernel=hparams.kernel,
#     )

#     model = dkl_Phison_mo.DKL(model, gp)

#     likelihood = SoftmaxLikelihood(num_classes=num_classes, mixing_weights=False)
#     likelihood = likelihood.cuda()

#     elbo_fn = VariationalELBO(likelihood, gp, num_data=len(train_com_dataset))
#     loss_fn = lambda x, y: -elbo_fn(x, y)
#     model = model.cuda()
    gpmodel_s1, model, likelihood, loss_fn = set_gpmodel(hparams, train_com_loader, train_com_dataset, num_classes)
    
#     params_cls = []
#     for key, value in dict(model.named_parameters()).items():
#         if value.requires_grad:
#             if "com_out" not in key:
#                 if "component_classifier" not in key:
#                     params_cls += [{'params': [value], 'lr': hparams.learning_rate, 'weight_decay': hparams.weight_decay}]
                
#     if hparams.likelihood == True:
#         print('likelihood :' , hparams.likelihood)
#         params_cls += [{'params': likelihood_cls.parameters()}]
        
#     optimizer = torch.optim.SGD(params_cls,
#                                 lr=hparams.learning_rate,
#                               momentum=0.9,
#                               weight_decay= hparams.weight_decay)
    
    params_com = []
    for key, value in dict(model.named_parameters()).items():
        if value.requires_grad:
            if "feature_extractor" not in key:
                params_com += [{'params': [value], 'lr': hparams.learning_rate, 'weight_decay': hparams.weight_decay}]
                
    if hparams.likelihood == True:
        params_com += [{'params': likelihood.parameters()}]
        
    optimizer_com = torch.optim.SGD(
        params_com,
        lr=hparams.learning_rate,
        momentum=0.9,
        weight_decay=hparams.weight_decay,
    )

    milestones = [35, 40, 45]
    milestones_com = [35, 40, 45]

#     scheduler = torch.optim.lr_scheduler.MultiStepLR(
#         optimizer, milestones=milestones, gamma=0.1
#     )
    scheduler2 = torch.optim.lr_scheduler.MultiStepLR(
        optimizer_com, milestones=milestones_com, gamma=0.1
    )

    

    def cycle(iterable):
        while True:
            for i in iterable:
                yield i

    train_loader_iter = cycle(train_loader)
    train_com_loader_iter = cycle(train_com_loader)

    def update(engine, _):   
        
        gpmodel_s1.eval()
#         model.eval()
#         likelihood.eval()

#         optimizer.zero_grad()

        # Class classifier
#         batch = next(train_loader_iter)
        
#         x, y, _, _ =  batch
#         x, y = x.cuda(), y.cuda()
#         y_cls, _ = model(x)
#         loss_cls = loss_fn_cls(y_cls, y)
        
#         loss_cls.backward(retain_graph=True)
#         optimizer.step()
        
        # Component classifier
        optimizer_com.zero_grad()
        batch = next(train_com_loader_iter)
        x2, _, _, y2 = batch

        x2, y2 = x2.cuda(), y2.cuda()
        _, y_com = gpmodel_s1(x2)
        
        model.train()
        likelihood.train()
        y_com_s2 = model(y_com)
#         import pdb;pdb.set_trace()
        loss_com = loss_fn(y_com_s2, y2)
        
        loss_com.backward()
        optimizer_com.step()
        
        loss = loss_com #loss_cls + loss_com
        return loss.item()
        

    trainer = Engine(update)

    num_iters = len(train_com_loader)  
    data = list(range(num_iters))

    
    def eval_step(engine, batch):
        model.eval()
        gpmodel_s1.eval()
        if not hparams.sngp:
            likelihood.eval()

        x, gt_cls, _, gt_com = batch
        x, gt_cls, gt_com = x.cuda(), gt_cls.cuda(), gt_com.cuda()
        
        with torch.no_grad():
            
            y_cls, y_com = gpmodel_s1(x)
            y_com_s2 = model(y_com)
        
        return y_com_s2, gt_com

#     def eval_step2(engine, batch):
#         model.eval()
#         if not hparams.sngp:
#             likelihood.eval()

#         x, gt_cls, _, gt_com = batch
#         x, gt_cls, gt_com = x.cuda(), gt_cls.cuda(), gt_com.cuda()
        
#         with torch.no_grad():
#             y_cls, y_com = model(x)   
            
#         return y_cls, gt_cls


#     def eval_step(engine, batch):
#         model.eval()
#         if not hparams.sngp:
#             likelihood.eval()

#         x, gt_cls, _, gt_com = batch
#         x, gt_cls, gt_com = x.cuda(), gt_cls.cuda(), gt_com.cuda()

#         with torch.no_grad():
#             y_cls, y_com = model(x)
#             with gpytorch.settings.num_likelihood_samples(32):
#             _ , y_com = model(x).to_data_independent_dist()
#             output = likelihood(y_com).probs.mean(0)

#         uncertainty = -(output * output.log()).sum(1)

#         return y_com, gt_com
#     

    evaluator = Engine(eval_step)
#     evaluator2 = Engine(eval_step2)
    
    metric = Average()
    metric.attach(trainer, "loss")
    
    def output_transform(output):
        y_pred, y = output

        # Sample softmax values independently for classification at test time
        y_pred = y_pred.to_data_independent_dist()

        # The mean here is over likelihood samples
        y_pred = likelihood(y_pred).probs.mean(0)

        return y_pred, y

#     def output_transform_cls(output):
#         y_pred_cls, y_cls = output

#         # Sample softmax values independently for classification at test time
#         y_pred_cls = y_pred_cls.to_data_independent_dist()

#         # The mean here is over likelihood samples
#         y_pred_cls = likelihood_cls(y_pred_cls).probs.mean(0)

#         return y_pred_cls, y_cls

    metric = Accuracy(output_transform=output_transform)
    metric.attach(evaluator, "accuracy")

#     metric = Accuracy(output_transform=output_transform_cls)
#     metric = Accuracy()
#     metric.attach(evaluator2, "accuracy_cls")


    metric = Loss(lambda y_pred, y: -likelihood.expected_log_prob(y, y_pred).mean())
    metric.attach(evaluator, "loss")

#     metric = Loss(lambda y_pred_cls, y_cls: -likelihood_cls.expected_log_prob(y_cls, y_pred_cls).mean())
#     metric.attach(evaluator2, "loss")
#     metric = Loss(F.cross_entropy)
#     metric.attach(evaluator2, "loss")


    
    
    kwargs = {"num_workers": 8, "pin_memory": True}

    test_loader = torch.utils.data.DataLoader(
        test_dataset, batch_size=128, shuffle=False, **kwargs
    )
    test_com_loader = torch.utils.data.DataLoader(
        test_com_dataset, batch_size=128, shuffle=False, **kwargs
    )


        
    @trainer.on(Events.EPOCH_COMPLETED)
    def log_results(trainer):
        metrics = trainer.state.metrics
        train_loss = metrics["loss"]

        result = f"Train - Epoch: {trainer.state.epoch} "
        if hparams.sngp:
            result += f"Loss: {train_loss:.2f} "
        else:
            result += f"ELBO: {train_loss:.2f} "
        print(result)

        writer.add_scalar("Loss/train", train_loss, trainer.state.epoch)

#         if hparams.spectral_conv:
#             for name, layer in model.feature_extractor.named_modules():
#                 if isinstance(layer, torch.nn.Conv2d):
#                     writer.add_scalar(
#                         f"sigma/{name}", layer.weight_sigma, trainer.state.epoch
#                     )

#         if trainer.state.epoch > 150 and trainer.state.epoch % 5 == 0:
#         _, auroc, aupr = get_ood_metrics(
#             train_dataset, test_dataset, model, likelihood, hparams.data_root
#         )
#         print(f"OoD Metrics - AUROC: {auroc}, AUPR: {aupr}")
#         writer.add_scalar("OoD/auroc", auroc, trainer.state.epoch)
#         writer.add_scalar("OoD/auprc", aupr, trainer.state.epoch)

        evaluator.run(test_com_loader)
        metrics = evaluator.state.metrics
        acc = metrics["accuracy"]
        test_com_loss = metrics["loss"]
        
#         evaluator2.run(test_loader)
#         metrics = evaluator2.state.metrics
#         acc_cls = metrics["accuracy_cls"]
#         test_cls_loss = metrics["loss"]
        
        test_loss = test_com_loss #+ test_cls_loss
        
        result = f"Test - Epoch: {trainer.state.epoch} "
        if hparams.sngp:
            result += f"Loss: {test_loss:.2f} "
        else:
            result += f"NLL: {test_loss:.2f} "
        result += f"Acc: {acc:.4f} "
#         result += f"Acc_cls: {acc_cls:.4f} "
        print(result)
        writer.add_scalar("Loss/test", test_loss, trainer.state.epoch)
        writer.add_scalar("Accuracy/test", acc, trainer.state.epoch)
#         writer.add_scalar("Accuracy_cls/test", acc_cls, trainer.state.epoch)

#         path = str(results_dir) +"/likelihood_"+ str(trainer.state.epoch) + ".pt"
#         torch.save(likelihood.state_dict(), path)

#         path_cls = str(results_dir) +"/likelihood_cls_"+ str(trainer.state.epoch) + ".pt"
#         torch.save(likelihood_cls.state_dict(), path_cls)


#         scheduler.step()
        scheduler2.step()

    pbar = ProgressBar(dynamic_ncols=True)
    pbar.attach(trainer)



#     @trainer.on(Events.EPOCH_COMPLETED)
#     def save_model():

#         print('best_loss:',best_loss)
#         now_loss = run_validation()
#         if best_loss > now_loss:
#             best_loss = now_loss
#             save_file = os.path.join(hparams.output_dir, 'MoV3_MLP.pth')
#             torch.save(model, save_file)


    
    

    # --- Save Model ---
    to_save = {'model': model}
            
    def run_validation(engine):
#         evaluator.run(test_loader)
        metrics = evaluator.state.metrics
        val_com_loss = metrics["loss"]
#         evaluator2.run(test_loader)
#         metrics = evaluator2.state.metrics
#         val_cls_loss = metrics["loss"]
        val_loss = val_com_loss #+ val_cls_loss
        
        return -val_loss
    
    handler = Checkpoint(
        to_save, results_dir,
        n_saved=3, filename_prefix='best',
        score_function=run_validation,
        score_name="loss",
        global_step_transform=global_step_from_engine(trainer)
    )

    evaluator.add_event_handler(Events.COMPLETED, handler)
    
        # --- Early_stopping ---

    handler = EarlyStopping(patience=15, score_function=run_validation, trainer=trainer)
    # Note: the handler is attached to an *Evaluator* (runs one epoch on validation dataset).
    evaluator.add_event_handler(Events.COMPLETED, handler)

    trainer.run(data,  max_epochs=50)
    # Done training - time to evaluate
    results = {}

#     evaluator.run(test_loader)
#     test_acc = evaluator.state.metrics["accuracy"]
#     test_loss = evaluator.state.metrics["loss"]
#     results["test_accuracy"] = test_acc
#     results["test_loss"] = test_loss

    
    

    #--- ood ---
#     _, auroc, aupr = get_ood_metrics(
#         train_dataset, test_dataset, model, likelihood, hparams.data_root
#     )
#     results["auroc_ood_svhn"] = auroc
#     results["aupr_ood_svhn"] = aupr

#     print(f"Final accuracy {results['test_accuracy']:.4f}")

#     results_json = json.dumps(results, indent=4, sort_keys=True)
#     (results_dir / "results.json").write_text(results_json)

    torch.save(model.state_dict(), results_dir / "model.pt")
    if likelihood is not None:
        torch.save(likelihood.state_dict(), results_dir / "likelihood.pt")
        
        
        
    

    writer.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--batch_size", type=int, default=128, help="Batch size to use for training"
    )

    parser.add_argument(
        "--learning_rate",
        type=float,
        default=0.05,
        help="Learning rate",
    )

    parser.add_argument("--weight_decay", type=float, default=0.0001, help="Weight decay")

    parser.add_argument("--dropout_rate", type=float, default=0.3, help="Dropout rate")

    parser.add_argument(
        "--dataset",
        default="fruit_8",
        choices=["CIFAR10", "CIFAR100", "PHISON" ,'PHISON_regroup','PHISON_regroup2','fruit','fruit_8'],
        help="Pick a dataset",
    )

    parser.add_argument(
        "--kernel",
        default="RBF",
        choices=["RBF", "RQ", "Matern12", "Matern32", "Matern52"],
        help="Pick a kernel",
    )

    parser.add_argument(
        "--no_spectral_conv",
        action="store_false",
        dest="spectral_conv",
        help="Don't use spectral normalization on the convolutions",
    )

    parser.add_argument(
        "--no_spectral_bn",
        action="store_false",
        dest="spectral_bn",
        help="Don't use spectral normalization on the batch normalization layers",
    )

    parser.add_argument(
        "--sngp",
        action="store_true",
        help="Use SNGP (RFF and Laplace) instead of a DUE (sparse GP)",
    )
    parser.add_argument(
        "--likelihood",
        action="store_true",
        help="Use SNGP (RFF and Laplace) instead of a DUE (sparse GP)",
    )
    parser.add_argument(
        "--n_inducing_points", type=int, help="Number of inducing points"
    )

    parser.add_argument("--seed", type=int, default=1 , help="Seed to use for training")

    parser.add_argument(
        "--coeff", type=float, default=1, help="Spectral normalization coefficient"
    )

    parser.add_argument(
        "--n_power_iterations", default=1, type=int, help="Number of power iterations"
    )

    parser.add_argument(
        "--output_dir", default="./default", type=str, help="Specify output directory"
    )
    parser.add_argument(
        "--data_root", default="./data", type=str, help="Specify data directory"
    )
    parser.add_argument(
        "-c", "--checkpoint_path",
        type=str,
        default ="",      # checkpoint.pth.tar
        help="Path to model's checkpoint."
    )

    args = parser.parse_args()
    hparams = Hyperparameters(**vars(args))

    main(hparams)
