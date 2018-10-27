import yaml

from arguments import Arguments
from cs_logger import CSLogger


class Params(Arguments):

    def __init__(self, params_filepath='./params.yaml'):
        """
        Init a class with all the parameters in the default YAML file.
        For each of them, create a new class attribute, with the same name
        but preceded by '_' character.
        """
        super(Params, self).__init__()

        with open(params_filepath, 'r') as stream:
            try:
                self.params = yaml.load(stream)
            except yaml.YAMLError as exc:
                print(exc)

        for param_name in self.params.keys():
            attribute_name = '_{}'.format(param_name)
            setattr(self, attribute_name, self.params[param_name])

        # Overwrite attributes specified by argument.
        if self.arg_window_size is not None:
            self._window_size = self.arg_window_size
        if self.arg_ticks_file is not None:
            self._ticks_file = self.arg_ticks_file

        # Start the logger
        self.log = CSLogger(self._log_level)

    @property
    def do_train(self):
        return self._train is True

    @property
    def model_names(self):
        return self._model_names

    @property
    def subtypes(self):
        return self._subtypes

    @property
    def max_tick_series_length(self):
        return self._max_tick_series_length