import pandas as pd
import numpy as np
import yaml
import matplotlib.pyplot as plt

from datetime import datetime
from keras.layers import LSTM, Dense, Dropout
from keras.models import Sequential, model_from_json
from keras.utils import to_categorical
from os.path import join, basename, splitext
from pathlib import Path
from sklearn.model_selection import train_test_split


class ValidationException(Exception):
    pass


class Csnn(object):

    _num_categories = 0
    _window_size = 3
    _num_predictions = 1
    _test_size = 0.1
    _dropout = 0.1
    _history = None
    _enc_data = None
    _raw_data = None
    _input_file = ''

    # metadata
    _metadata = {'period': 'unk', 'epochs': 'unk', 'accuracy': 'unk'}

    # Files output
    _output_dir = ''

    # Model design
    _l1units = 256
    _l2units = 256
    _activation = 'sigmoid'

    # Training
    _epochs = 100
    _batch_size = 10
    _validation_split = 0.1
    _verbose = 1

    # Compilation
    _loss = 'mean_squared_error'
    _optimizer = 'adam'
    _metrics = ['accuracy']

    # Results
    _history = None

    X_train = None
    y_train = None
    X_test = None
    y_test = None

    def __init__(self):
        pass

    def init(self, params_filepath):
        """
        Init the class with the number of categories used to encode candles
        """
        with open(params_filepath, 'r') as stream:
            try:
                self.params = yaml.load(stream)
            except yaml.YAMLError as exc:
                print(exc)

        # Get the list of object parameters
        # attributes = inspect.getmembers(self,
        #                                 lambda a: not (inspect.isroutine(a)))
        # attribute_names = [
        #     a[0] for a in attributes
        #     if not (a[0].startswith('__') and a[0].endswith('__'))
        # ]

        # Override internal attributes with param values if name matches
        # for attribute in attribute_names:
        #     if attribute.startswith('_') and attribute[1:] in self.params:
        #         setattr(self, attribute, self.params[attribute[1:]])
        for param_name in self.params.keys():
            attribute_name = '_{}'.format(param_name)
            setattr(self, attribute_name, self.params[param_name])
        self._metadata['dataset'] = splitext(basename(self._input_file))[0]
        self._metadata['epochs'] = self._epochs
        return self

    def valid_samples(self, x, all=False):
        """
        Given a candidate number for the total number of samples to be considered
        for training and test, this function simply substract the number of
        test cases, predictions and timesteps from it.
        """
        if all is True:
            return x
        return (x - self._num_testcases - self._window_size -
                self._num_predictions)

    def find_largest_divisor(self, x, all=False):
        """
        Compute a number lower or equal to 'x' that is divisible by the divsor
        passed as second argument. The flag 'all' informs the function whether
        the number of samples can be used as such (all=True) or it must be
        adjusted substracting the number of test cases, predictions and
        num_timesteps from it.
        """
        found = False
        while x > 0 and found is False:
            if self.valid_samples(x, all) % self._batch_size is 0:
                found = True
            else:
                x -= 1
        return x

    def adjust(self, raw):
        """
        Given a raw sequence of samples, it determines the correct number of
        samples that can be used, given the amount of test cases requested,
        the timesteps, the nr of predictions, and the batch_size.
        Returns the raw sequence of samples adjusted, by removing the first
        elements from the array until shape fulfills TensorFlow conditions.
        """
        self._num_samples = raw.shape[0]
        self._num_testcases = int(self._num_samples * self._test_size)
        new_testshape = self.find_largest_divisor(
            self._num_testcases, all=True)
        # print('Reshaping TEST from [{}] to [{}]'.format(
        #     self._num_testcases, new_testshape))
        self._num_testcases = new_testshape

        new_shape = self.find_largest_divisor(raw.shape[0], all=False)
        # print('Reshaping RAW from [{}] to [{}]'.format(raw.shape,
        #                                                raw[-new_shape:].shape))
        new_df = raw[-new_shape:].reset_index().drop(['index'], axis=1)
        self.params['adj_numrows'] = new_df.shape[0]
        self.params['adj_numcols'] = new_df.shape[1]

        # Setup the windowing of the dataset.
        self._num_samples = raw.shape[0]
        self._num_features = raw.shape[1] if len(raw.shape) > 1 else 1
        self._num_frames = self._num_samples - (
            self._window_size + self._num_predictions) + 1

        return new_df

    def onehot_encode(self):
        """
        Transform the content of a Dataframe with encoded candlesticks
        into a one_hot encoding
        """
        self.to_numerical()
        self._enc_data = pd.DataFrame(
            to_categorical(self._num_data, num_classes=self._num_categories))
        return self._enc_data

    def read_file(self, filename=None):
        """
        Read the file and return a Series object with a column called 'cse'
        """
        if filename is None:
            f_name = self._input_file
        else:
            f_name = filename
        f = pd.read_csv(f_name, 'r', header='infer', delimiter=',')
        self._raw_data = f['body']
        return f['body']

    def build_encoding_equation(self, n, min, max):
        x1 = 0
        x2 = n - 1
        y1 = min
        y2 = max
        m = (y2 - y1) / (x2 - x1)
        b = y1 - (m * x1)
        return lambda x: float('{0:.2f}'.format(((m * x) + b)))

    def build_dictionary(self, data, regression=False):
        unique_values = sorted(data.unique())
        if regression is True:
            eq = self.build_encoding_equation(len(unique_values), -1.0, +1.0)
            dictionary = {
                value: eq(idx)
                for (idx, value) in enumerate(unique_values)
            }
        else:
            dictionary = {
                value: idx
                for (idx, value) in enumerate(unique_values)
            }
        return dictionary

    def set_metadata(self, property, value):
        self._metadata[property] = value

    def encode(self, raw_data, dictionary):
        return raw_data.apply(lambda v: dictionary[v])

    def to_numerical(self):
        """
        Tranform the codes used to encode the different candlesticks into
        a different number for each of the categories.
        """
        dictionary = self.build_dictionary(self._raw_data)
        df = self._raw_data.apply(lambda ev: dictionary[ev])
        self._num_data = df
        return df

    # frame a sequence as a supervised learning problem
    def timeseries_to_supervised(self, data, lag=1):
        df = pd.DataFrame(data)
        columns = [df.shift(i) for i in range(1, lag + 1)]
        columns.append(df)
        df = pd.concat(columns, axis=1)
        df.fillna(0, inplace=True)
        return train_test_split(
            df, test_size=self.params['_test_size'], shuffle=False)

    def reshape(self, data):
        num_entries = data.shape[0] * data.shape[1]
        timesteps = self._window_size + 1
        num_samples = int((num_entries / self._num_categories) / timesteps)
        train = data.reshape((num_samples, timesteps, self._num_categories))
        X_train = train[:, 0:self._window_size, :]
        y_train = train[:, -1, :]
        return X_train, y_train

    def to_slidingwindow_series(self, window_size, test_size):
        series = self._enc_data.copy()
        series_s = series.copy()
        for i in range(window_size):
            series = pd.concat([series, series_s.shift(-(i + 1))], axis=1)
        series.dropna(axis=0, inplace=True)
        train, test = train_test_split(
            series, test_size=test_size, shuffle=False)
        self.X_train, self.y_train = self.reshape(np.array(train))
        self.X_test, self.y_test = self.reshape(np.array(test))
        return self.X_train, self.y_train, self.X_test, self.y_test

    def build_model(self, summary=True):
        """
        Builds the model according to the parameters specified for
        dropout, num of categories in the output, window size,
        """
        model = Sequential()
        model.add(
            LSTM(
                input_shape=(self._window_size, self._num_categories),
                return_sequences=True,
                units=self._l1units))
        model.add(Dropout(self._dropout))
        model.add(LSTM(self._l2units))
        model.add(Dropout(self._dropout))
        model.add(Dense(self._num_categories, activation=self._activation))
        # model.add(Activation("tanh"))
        model.compile(
            loss=self._loss, optimizer=self._optimizer, metrics=self._metrics)
        if summary is True:
            model.summary()
        return model

    def train(self, model):
        """
        Train the model and put the history in an internal stateself.
        Metadata is updated with the accuracy
        """
        self._history = model.fit(
            self.X_train,
            self.y_train,
            epochs=self._epochs,
            batch_size=self._batch_size,
            verbose=self._verbose,
            validation_split=self._validation_split)
        self._meta['accuracy'] = self._history.history['acc']
        return self._history

    def predict(self):
        """
        Make a prediction over the internal X_test set.
        """
        self._yhat = self._model.predict(self.X_test)
        return self._yhat

    def valid_output_name(self):
        """
        Builds a valid name with the metadata and the date.
        Returns The filename if the name is valid and file does not exists,
                None otherwise.
        """
        self._filename = 'model_{}_{}_{}_{}'.format(
            datetime.now().strftime('%Y%m%d_%H%M'), self._metadata['dataset'],
            self._metadata['epochs'], self._metadata['accuracy'])
        base_filepath = join(self._output_dir, self._filename)
        output_filepath = base_filepath
        idx = 1
        while Path(output_filepath).is_file() is True:
            output_filepath = '{}_{:d}'.format(base_filepath + idx)
            idx += 1
        return output_filepath

    def load_model(self, modelname, summary=True):
        """ load json and create model """
        json_file = open('{}.json'.format(modelname), 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        loaded_model = model_from_json(loaded_model_json)
        # load weights into new model
        loaded_model.load_weights('{}.h5'.format(modelname))
        print("Loaded model from disk")
        loaded_model.compile(
            loss='mean_squared_error', optimizer='adam', metrics=['accuracy'])
        if summary is True:
            loaded_model.summary()
        self._model = loaded_model
        return loaded_model

    def save_model(self, modelname=None):
        """ serialize model to JSON """
        if self._metadata['accuracy'] == 'unk':
            raise ValidationException('Trying to save without training.')
        if modelname is None:
            modelname = self.valid_output_name()
        model_json = self._model.to_json()
        with open('{}.json'.format(modelname), "w") as json_file:
            json_file.write(model_json)
        # serialize weights to HDF5
        self._model.save_weights('{}.h5'.format(modelname))
        print("Saved model and weights to disk")

    def plot_history(self):
        if self._history is None:
            raise ValidationException('Trying to plot without training')
        """ summarize history for accuracy and loss """
        plt.plot(self._history.history['acc'])
        plt.plot(self._history.history['val_acc'])
        plt.title('model accuracy')
        plt.ylabel('accuracy')
        plt.xlabel('epoch')
        plt.legend(['train', 'test'], loc='upper left')
        plt.show()

        plt.plot(self._history.history['loss'])
        plt.plot(self._history.history['val_loss'])
        plt.title('model loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        plt.legend(['train', 'test'], loc='upper left')
        plt.show()
