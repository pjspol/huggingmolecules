from typing import Optional, Callable, Type

import pytorch_lightning as pl
import torch
from torchmetrics import Metric
from torch import nn
from torch import Tensor

from experiments.src.training.training_metrics import BatchWeightedLoss
from src.huggingmolecules.featurization.featurization_api import BatchEncodingProtocol
from src.huggingmolecules.models.models_api import PretrainedModelBase


class TrainingModule(pl.LightningModule):
    def __init__(self,
                 model: PretrainedModelBase, *,
                 loss_fn: Callable[[Tensor, Tensor], Tensor],
                 optimizer: torch.optim.Optimizer,
                 metric_cls: Type[Metric]):
        super().__init__()
        self.model = model
        self.loss_fn = loss_fn
        self.optimizer = optimizer

        self.weighted_loss = nn.ModuleDict({phase: BatchWeightedLoss() for phase in ['train_set', 'valid_set', 'test_set']})
        self.metric = nn.ModuleDict({phase: metric_cls() for phase in ['train_set', 'valid_set', 'test_set']})
        self.metric_name = metric_cls.__name__.lower()

    def cuda(self, device: Optional[int] = None):
        setattr(self.model, 'device', device)
        return super(TrainingModule, self).cuda(device)

    def forward(self, batch: BatchEncodingProtocol):
        return self.model.forward(batch)

    def _step(self, mode: str, batch: BatchEncodingProtocol, batch_idx: int) -> torch.Tensor:
        output = self.forward(batch)
        loss = self.loss_fn(output, batch.y)
        preds = torch.mean(torch.stack(output), dim=0) if isinstance(output, tuple) else output

        self.weighted_loss[mode](loss, len(batch))
        self.metric[mode](preds.cpu(), batch.y.cpu())

        self.log(f'{mode}_loss', self.weighted_loss[mode], on_epoch=True, on_step=False, sync_dist=True)
        self.log(f'{mode}_{self.metric_name}', self.metric[mode], on_epoch=True, on_step=False, sync_dist=True)

        return loss

    def on_train_epoch_start(self) -> None:
        self.weighted_loss['train_set'].reset()
        self.metric['train_set'].reset()

    def training_step(self, batch: BatchEncodingProtocol, batch_idx: int) -> torch.Tensor:
        return self._step('train_set', batch, batch_idx)

    #def validation_step(self, batch: BatchEncodingProtocol, batch_idx: int) -> torch.Tensor:
        #return self._step('valid_set', batch, batch_idx)

    def test_step(self, batch: BatchEncodingProtocol, batch_idx: int) -> torch.Tensor:
        return self._step('test_set', batch, batch_idx)

    def configure_optimizers(self) -> torch.optim.Optimizer:
        return self.optimizer
