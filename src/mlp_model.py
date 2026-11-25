"""A CPU multilayer perceptron for binary classification."""

from torch import nn


class FailureMLP(nn.Module):
    INPUT_SIZE = 8
    HIDDEN_SIZES = (32, 16)

    def __init__(self):
        super().__init__()
        first, second = self.HIDDEN_SIZES
        self.network = nn.Sequential(
            nn.Linear(self.INPUT_SIZE, first),
            nn.ReLU(),
            nn.Linear(first, second),
            nn.ReLU(),
            nn.Linear(second, 1),
        )

    def forward(self, features):
        """Return one raw logit per row, including for a one-row batch."""
        return self.network(features).squeeze(-1)
