import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as Data
from sklearn.metrics import accuracy_score


def get_device():
    if torch.cuda.is_available():
        device = 'cuda:0'
    else:
        device = 'cpu'
    print(device)
    return('cpu')
    return device

class ModelAutoEncoder(nn.Module):
    def __init__(self, num_features):
        super(ModelAutoEncoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(num_features, 50),
            nn.ReLU(True),
            nn.Linear(50, 25),
            nn.ReLU(True), nn.Linear(25, 10))
        self.decoder = nn.Sequential(
            nn.Linear(10, 25),
            nn.ReLU(True),
            nn.Linear(25, 50),
            nn.ReLU(True),
            nn.Linear(50, num_features), nn.Tanh())
        self.classifier = nn.Linear(10, 2)
        self.supervised = True
    def forward(self, x):
        x = self.encoder(x)
        if self.supervised:
            x = F.log_softmax(self.classifier(x), dim=1)
            return x
        x = self.decoder(x)
        return x
    def set_supervised_flag(self,supervised):
        self.supervised = supervised


class AutoEncoderChain():
    def __init__(self, num_features):
        self._model = ModelAutoEncoder(num_features).double()
        self._criterion = nn.MSELoss()
        self._criterion_classify = nn.CrossEntropyLoss()
        self._optimizer = torch.optim.Adam(self._model.parameters(), lr=0.001)
        self._log_interval = 100
        self._device = get_device()
        self._model = self._model.to(self._device)

    def train_model(self, feature_labeled, feature_unlabeled, label, test_feature, test_label, epoch=10, batch_size=64):
        train_data_labeled = Data.TensorDataset(torch.from_numpy(feature_labeled), torch.from_numpy(label))
        train_data_unlabeled = Data.TensorDataset(torch.from_numpy(feature_unlabeled), torch.from_numpy(feature_unlabeled))
        train_loader_labeled = Data.DataLoader(dataset=train_data_labeled, batch_size=batch_size, shuffle=True)
        train_loader_unlabeled = Data.DataLoader(dataset=train_data_unlabeled, batch_size=batch_size, shuffle=True)
        self._model.train()
        for epoch_id in range(10):
            train_loss = 0
            self._model.set_supervised_flag(False)
            for step, (train_batch, _) in enumerate(train_loader_unlabeled):
                train_batch = train_batch.to(self._device)
                decoded = self._model(train_batch)
                loss = self._criterion(decoded, train_batch)
                self._optimizer.zero_grad()
                loss.backward()
                train_loss += loss.data.cpu().numpy()
                self._optimizer.step()
                if (step + 1) % self._log_interval == 0:
                    print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.8f}'.format(
                        epoch_id, (step + 1)* len(train_batch), len(train_loader_unlabeled.dataset),
                        100. * (step + 1) / len(train_loader_unlabeled), train_loss / self._log_interval))
                    train_loss = 0

        for k,v in self._model.named_parameters():
            if k[:10] != 'classifier':
                v.requires_grad = False
        self._optimizer = torch.optim.Adam(self._model.parameters(), lr=0.001)
        for epoch_id in range(epoch):
            train_loss = 0
            self._model.set_supervised_flag(True)
            for step, (train_batch, train_label) in enumerate(train_loader_labeled):
                train_batch = train_batch.to(self._device)
                train_label = train_label.to(self._device)
                decoded = self._model(train_batch)
                loss = self._criterion_classify(decoded, train_label.long())
                self._optimizer.zero_grad()
                loss.backward()
                train_loss += loss.data.cpu().numpy()
                self._optimizer.step()
                if (step + 1) % self._log_interval == 0:
                    print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.8f}'.format(
                        epoch_id, (step + 1)* len(train_batch), len(train_loader_labeled.dataset),
                        100. * (step + 1) / len(train_loader_labeled), train_loss / self._log_interval))
                    train_loss = 0
            val_label, val_score = self.evaluate_model(test_feature, test_label)
            self._model.train()
            accuracy = accuracy_score(test_label, val_label)
            print('Validation Data Accuray = %.6lf' %(accuracy))



    def get_distance(self, X, Y):
        euclidean_sq = np.square(Y - X)
        return np.sqrt(np.sum(euclidean_sq, axis=1)).ravel()

    def evaluate_model(self, feature, label):
        self._model.eval()
        test_data = Data.TensorDataset(torch.from_numpy(feature), torch.from_numpy(label))
        test_loader = Data.DataLoader(dataset=test_data, batch_size=64, shuffle=False)
        output_feature = []
        output_label = []
        test_loss = 0
        ss = 0
        for test_batch, test_label in test_loader:
            test_batch = test_batch.to(self._device)
            test_label = test_label.to(self._device)
            self._model.set_supervised_flag(False)
            output = self._model(test_batch)
            output_feature.append(output.data.cpu().numpy())
            test_loss += self._criterion(output, test_batch).data.cpu().numpy()

            self._model.set_supervised_flag(True)

            output = self._model(test_batch)
            _, predicted = torch.max(output.data, 1)
            h = predicted.cpu().numpy()
            ss += sum(h)
            output_label.append(h)

        test_loss /= len(test_loader)                                           # loss function already averages over batch size
        print(ss)
        print('\nTesting set: Average loss: {:.4f}\n'.format(
        test_loss))
        predicted_score = np.concatenate(output_feature, axis=0)
        predicted_label = np.concatenate(output_label, axis=0)
        return predicted_label, self.get_distance(feature, predicted_score)
