import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as Data

from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from torch.autograd import Variable


#os.environ["CUDA_VISIBLE_DEVICES"] = "6"
# use_cuda = torch.cuda.is_available()
# device = torch.device("cuda:6" if use_cuda else "cpu")
# cudnn.benchmark = True

CUDA = 'cuda:4'

def get_device():
    if torch.cuda.is_available():
        device = CUDA
    else:
        device = 'cpu'
    print(device)
    return device

def print_confidence_each_class(predicted_score, raw_label):
    sum_classes = {}
    num_classes = {}
    # h = []
    for i in range(len(predicted_score)):
        if raw_label[i] not in sum_classes:
            sum_classes[raw_label[i]] = 0
            num_classes[raw_label[i]] = 0
        # if raw_label[i] == FILTER_CLASS_NAME:
            # h.append(predicted_score[i])
            # print("class:%s confidence:%.6lf classify:%.6lf" %(raw_label[i], confidence[i], predicted_score[i]))
        sum_classes[raw_label[i]] += predicted_score[i]
        num_classes[raw_label[i]] += 1
    # print(h)
    for p in sum_classes:
        print("confidence of %s: %.6lf" %(p, sum_classes[p] / num_classes[p]))

class FocalLoss(nn.Module):
    r"""
        This criterion is a implemenation of Focal Loss, which is proposed in 
        Focal Loss for Dense Object Detection.

            Loss(x, class) = - \alpha (1-softmax(x)[class])^gamma \log(softmax(x)[class])

        The losses are averaged across observations for each minibatch.

        Args:
            alpha(1D Tensor, Variable) : the scalar factor for this criterion
            gamma(float, double) : gamma > 0; reduces the relative loss for well-classiﬁed examples (p > .5), 
                                   putting more focus on hard, misclassiﬁed examples
            size_average(bool): By default, the losses are averaged over observations for each minibatch.
                                However, if the field size_average is set to False, the losses are
                                instead summed for each minibatch.


    """
    def __init__(self, class_num=2, alpha=None, gamma=2, size_average=True):
        super(FocalLoss, self).__init__()
        if alpha is None:
            self.alpha = Variable(torch.ones(class_num, 1))
        else:
            if isinstance(alpha, Variable):
                self.alpha = alpha
            else:
                self.alpha = Variable(alpha)
        self.gamma = gamma
        self.class_num = class_num
        self.size_average = size_average
        self._device = get_device()

    def forward(self, inputs, targets):
        N = inputs.size(0)
        C = inputs.size(1)
        P = F.softmax(inputs)

        class_mask = inputs.data.new(N, C).fill_(0)
        class_mask = Variable(class_mask)
        ids = targets.view(-1, 1)
        class_mask.scatter_(1, ids.data, 1.)
        #print(class_mask)


        alpha = self.alpha[ids.data.view(-1)].to(self._device)

        probs = (P*class_mask).sum(1).view(-1,1)

        log_p = probs.log()
        #print('probs size= {}'.format(probs.size()))
        #print(probs)

        batch_loss = -alpha*(torch.pow((1-probs), self.gamma))*log_p 
        #print('-----bacth_loss------')
        #print(batch_loss)


        if self.size_average:
            loss = batch_loss.mean()
        else:
            loss = batch_loss.sum()
        return loss

class ModelAutoEncoder(nn.Module):
    def __init__(self, num_features):
        super(ModelAutoEncoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(num_features, 100),
            nn.ReLU(True),
            nn.Linear(100, 80),
            nn.ReLU(True), nn.Linear(80, 10))
        self.decoder = nn.Sequential(
            nn.Linear(10, 80),
            nn.ReLU(True),
            nn.Linear(80, 100),
            nn.ReLU(True),
            nn.Linear(100, num_features), nn.Tanh())
        self.classifier = nn.Linear(10, 2)
        self.supervised = True


    def forward(self, x):
        x = self.encoder(x)
        if self.supervised:
            # x = F.log_softmax(self.classifier(x), dim=1)
            return self.classifier(x)
        x = self.decoder(x)
        return x

    def set_supervised_flag(self,supervised):
        self.supervised = supervised


class AutoEncoder():
    def __init__(self, num_features, device):
        global CUDA
        CUDA=device
        self._model = ModelAutoEncoder(num_features).double()
        self._device = get_device()
        self._criterion = nn.MSELoss()
        # self._criterion_classify = nn.CrossEntropyLoss()
        self._criterion_classify = FocalLoss()
        self._optimizer = torch.optim.Adam(self._model.parameters(), lr=0.001)
        self._log_interval = 100
        self._model = self._model.to(self._device)

    def train_model(self, train_labeled_data, feature_unlabeled, validate_data, epoch=10, batch_size=64):
        train_dataset_labeled = Data.TensorDataset(torch.from_numpy(train_labeled_data[0]), torch.from_numpy(train_labeled_data[1]))
        train_dataset_unlabeled = Data.TensorDataset(torch.from_numpy(feature_unlabeled))
        train_loader_labeled = Data.DataLoader(dataset=train_dataset_labeled, batch_size=batch_size, shuffle=True)
        train_loader_unlabeled = Data.DataLoader(dataset=train_dataset_unlabeled, batch_size=batch_size, shuffle=True)
        train_loss = 0; epoch_id = 0; step = 0
        iter_labeled = iter(train_loader_labeled)
        iter_unlabeled = iter(train_loader_unlabeled)
        self._model.train()
        while epoch_id < epoch:
            self._model.set_supervised_flag(True)
            try:
                train_batch, train_label = next(iter_labeled)
            except StopIteration:
                iter_labeled = iter(train_loader_labeled)
                train_batch, train_label = next(iter_labeled)

            train_batch = train_batch.to(self._device)
            train_label = train_label.to(self._device)
            decoded = self._model(train_batch)
            loss = self._criterion_classify(decoded, train_label.long())
            self._optimizer.zero_grad()
            loss.backward()
            train_loss += loss.data.cpu().numpy()
            self._optimizer.step()
            # if (step + 1) % self._log_interval == 0:
            #     print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.8f}'.format(
            #         epoch_id, (step + 1)* len(train_batch), len(train_loader_labeled.dataset),
            #         100. * (step + 1) / len(train_loader_labeled), train_loss / self._log_interval))
            #     train_loss = 0

            try:
                train_batch = next(iter_unlabeled)[0]
            except StopIteration:
                iter_unlabeled = iter(train_loader_unlabeled)
                epoch_id += 1
                step = 0
                train_loss = 0
                _, _, classify_score = self.evaluate_model(train_labeled_data)
                print_confidence_each_class(classify_score, train_labeled_data[2])
                val_label, val_score, classify_score = self.evaluate_model(validate_data)
                self._model.train()
                print_confidence_each_class(classify_score, validate_data[2])
                roc=roc_auc_score(validate_data[1], val_score)
                print("roc_autoencoder= %.6lf" %(roc))
                roc=roc_auc_score(validate_data[1], classify_score)
                print("roc_classify= %.6lf" %(roc))
                val_score = MinMaxScaler().fit_transform(val_score.reshape(-1, 1)).reshape(-1)
                # classify_score = StandardScaler().fit_transform(classify_score.reshape(-1, 1)).reshape(-1)
                val_score_1 = val_score + classify_score * classify_score
                roc=roc_auc_score(validate_data[1], val_score_1)
                print("roc_ensemble_square= %.6lf" %(roc))

                val_score_2 = val_score + classify_score
                roc=roc_auc_score(validate_data[1], val_score_2)
                print("roc_ensemble= %.6lf" %(roc))

                accuracy = accuracy_score(validate_data[1], val_label)
                f1 = f1_score(validate_data[1], val_label, average='binary', pos_label=1)
                # print('Validation Data Accuray = %.6lf' %(accuracy))
                print('Validation Data F1 Score = %.6lf' %(f1))
                train_batch = next(iter_unlabeled)[0]
            self._model.set_supervised_flag(False)
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

            step += 1


    def get_distance(self, X, Y):
        euclidean_sq = np.square(Y - X)
        return np.sqrt(np.sum(euclidean_sq, axis=1)).ravel()

    def evaluate_model(self, test_data):
        self._model.eval()
        test_dataset = Data.TensorDataset(torch.from_numpy(test_data[0]), torch.from_numpy(test_data[1]))
        test_loader = Data.DataLoader(dataset=test_dataset, batch_size=64, shuffle=False)
        output_feature = []
        output_label = []
        output_score = []
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
            output = F.softmax(output, dim=1)
            _, predicted = torch.max(output.data, 1)
            score = output.data[:, 1]
            h = predicted.cpu().numpy()
            ss += sum(h)
            output_label.append(h)
            output_score.append(score.cpu().numpy())

        test_loss /= len(test_loader)                                           # loss function already averages over batch size
        print(ss)
        print('\nTesting set: Average loss: {:.4f}\n'.format(
        test_loss))
        predicted_score = np.concatenate(output_feature, axis=0)
        predicted_label = np.concatenate(output_label, axis=0)
        classify_score = np.concatenate(output_score, axis=0)
        return predicted_label, self.get_distance(test_data[0], predicted_score), classify_score
