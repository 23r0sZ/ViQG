from torchtext.data import Example, Dataset, Field
from nltk.tokenize import word_tokenize

class HandleDataset(object):
    """VerbalDataset class"""

    def __init__(self, train, val, test):
        self.train = train
        self.val = val
        self.test = test
        self.train_data = None
        self.valid_data = None
        self.test_data = None
        self.src_field = None
        self.trg_field = None

    def _make_torchtext_dataset(self, data, fields):
        examples = [Example.fromlist(i, fields) for i in data]
        return Dataset(examples, fields)

    def load_data_and_fields(self):
        """
        Load verbalization data
        Create source and target fields
        """
        train, test, val = self.train, self.test, self.val

        # Create train examples
        train_examples = []
        for sample in train:
            context = sample["contexts"]
            answer = sample["answers"]
            question = sample["questions"]

            src = f"<s>{context}</s></s>{answer}</s>"
            trg = question

            train_examples.append((src, trg))

        # Create test examples
        test_examples = []
        for sample in test:
            context = sample["contexts"]
            answer = sample["answers"]
            question = sample["questions"]

            src = f"<s>{context}</s></s>{answer}</s>"
            trg = question

            test_examples.append((src, trg))

        # Create validation examples
        val_examples = []
        for sample in val:
            context = sample["contexts"]
            answer = sample["answers"]
            question = sample["questions"]

            src = f"<s>{context}</s></s>{answer}</s>"
            trg = question

            val_examples.append((src, trg))

        # Create fields
        self.src_field = Field(tokenize=word_tokenize,
                               init_token="<s>",
                               eos_token="</s>",
                               lower=True,
                               include_lengths=True,
                               batch_first=True)
        self.trg_field = Field(tokenize=word_tokenize,
                               init_token="<s>",
                               eos_token="</s>",
                               lower=True,
                               batch_first=True)

        fields_tuple = [("src", self.src_field), ("trg", self.trg_field)]

        # Create torchtext datasets
        self.train_data = self._make_torchtext_dataset(train_examples, fields_tuple)
        self.valid_data = self._make_torchtext_dataset(val_examples, fields_tuple)
        self.test_data = self._make_torchtext_dataset(test_examples, fields_tuple)

        # Build vocabularies
        self.src_field.build_vocab(self.train_data, min_freq=1)
        self.trg_field.build_vocab(self.train_data, min_freq=1)

    def get_data(self):
        """Return train, validation and test data objects"""
        return self.train_data, self.valid_data, self.test_data

    def get_fields(self):
        """Return source and target field objects"""
        return self.src_field, self.trg_field

    def get_vocabs(self):
        """Return source and target vocabularies"""
        return self.src_field.vocab, self.trg_field.vocab
