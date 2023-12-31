"""
Seq2seq based: Effective Approaches to Attention-based Neural Machine Translation
https://arxiv.org/abs/1508.04025
"""
import random
import torch
import torch.nn as nn
import torch.nn.functional as F
#from seq2seq.models.conf import PAD_TOKEN, EOS_TOKEN, SOS_TOKEN
#from seq2seq.models.layers import RNN, Embedding, Linear, LSTM, GRU

EOS_TOKEN = '<eos>'
SOS_TOKEN = '<sos>'
PAD_TOKEN = '<pad>'

def RNN(cell_name):
    if cell_name.lower() == 'lstm':
        return LSTM
    elif cell_name.lower() == 'gru':
        return GRU
    else:
        raise ValueError(f"Unsupported RNN Cell: {cell_name}")


def Embedding(num_embeddings, embedding_dim, padding_idx):
    """Embedding layer"""
    m = nn.Embedding(num_embeddings, embedding_dim, padding_idx=padding_idx)
    nn.init.uniform_(m.weight, -0.1, 0.1)
    nn.init.constant_(m.weight[padding_idx], 0)
    return m


def Linear(in_features, out_features, bias=True):
    """Linear layer"""
    m = nn.Linear(in_features, out_features, bias=bias)
    m.weight.data.uniform_(-0.1, 0.1)
    if bias:
        m.bias.data.uniform_(-0.1, 0.1)
    return m


def LSTM(input_size, hidden_size, **kwargs):
    """LSTM layer"""
    m = nn.LSTM(input_size, hidden_size, **kwargs)
    for name, param in m.named_parameters():
        if 'weight' in name or 'bias' in name:
            param.data.uniform_(-0.1, 0.1)
    return m


def GRU(input_size, hidden_size, **kwargs):
    """GRU layer"""
    m = nn.GRU(input_size, hidden_size, **kwargs)
    for name, param in m.named_parameters():
        if 'weight' in name or 'bias' in name:
            param.data.uniform_(-0.1, 0.1)
    return m


def Conv1d(in_channels, out_channels, kernel_size, padding=0):
    """Conv1d"""
    m = nn.Conv1d(in_channels=in_channels, out_channels=out_channels, kernel_size=kernel_size, padding=padding)
    nn.init.normal_(m.weight, 0, 0.1)
    nn.init.constant_(m.bias, 0)
    return m


def PositionalEmbedding(num_embeddings, embedding_dim, padding_idx):
    """PositionalEmbedding"""
    m = LearnedPositionalEmbedding(num_embeddings, embedding_dim, padding_idx)
    nn.init.normal_(m.weight, 0, 0.1)
    nn.init.constant_(m.weight[padding_idx], 0)
    return m


class LearnedPositionalEmbedding(nn.Embedding):
    """LearnedPositionalEmbedding"""

    def __init__(self, num_embeddings, embedding_dim, padding_idx):
        super().__init__(num_embeddings, embedding_dim, padding_idx)

    def forward(self, input):
        """Input size [bsz x seqlen]"""
        # Replace non-padding symbols with their position numbers.
        # Position numbers begin at padding_idx+1. Padding symbols are ignored.
        mask = input.ne(self.padding_idx).int()
        positions = (torch.cumsum(mask, dim=1).type_as(mask) * mask).long() + self.padding_idx
        return super().forward(positions)

class Encoder(nn.Module):
    """Encoder"""
    def __init__(self, vocabulary, device, cell_name, hidden_size=512, num_layers=2,
                 bidirectional=True, dropout=0.5):
        super().__init__()
        input_dim = len(vocabulary)
        self.num_layers = num_layers
        self.pad_id = vocabulary.stoi[PAD_TOKEN]
        self.hidden_size = hidden_size
        self.bidirectional = bidirectional
        self.device = device
        self.rnn_cell = RNN(cell_name)

        self.embedding = Embedding(input_dim, self.hidden_size, self.pad_id)
        self.dropout = dropout

        self.rnn = self.rnn_cell(
            input_size=self.hidden_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            batch_first=True,
            bidirectional=self.bidirectional,
            dropout=self.dropout if self.num_layers > 1 else 0.
        )

    def forward(self, src_tokens, **kwargs):
        """
        Forward Encoder
        Args:
            src_tokens (LongTensor): (batch, src_len)
            src_lengths (LongTensor): (batch)
        Returns:
            x (LongTensor): (src_len, batch, hidden_size * num_directions)
            hidden (LongTensor): (batch, enc_hid_dim)
        """
        src_lengths = kwargs.get('src_lengths', '')

        embedded = self.embedding(src_tokens)
        embedded = F.dropout(embedded, p=self.dropout, training=self.training)

        embedded = nn.utils.rnn.pack_padded_sequence(embedded, src_lengths.cpu(), batch_first=True)
        output, hidden = self.rnn(embedded)

        output, _ = nn.utils.rnn.pad_packed_sequence(output, batch_first=True)
        output = F.dropout(output, p=self.dropout, training=self.training)

        if isinstance(hidden, tuple):
            hidden = tuple([self._cat_directions(h) for h in hidden])
        else:
            hidden = self._cat_directions(hidden)

        return output, hidden

    def _cat_directions(self, h):
        """
        If the encoder is bidirectional, do the following transformation.
        (#directions * #layers, #batch, hidden_size) -> (#layers, #batch, #directions * hidden_size)
        """
        if self.bidirectional:
            h = torch.cat([h[0:h.size(0):2], h[1:h.size(0):2]], 2)
        return h

class Attention(nn.Module):
    """Attention"""
    def __init__(self, input_embed, source_embed, output_embed):
        super().__init__()
        self.linear_in = Linear(input_embed, source_embed)
        self.linear_out = Linear(input_embed+source_embed, output_embed)

    def forward(self, output, context, mask):
        """
        Forward Attention
        """
        # input: bsz x input_embed_dim
        # source_hids: srclen x bsz x source_embed_dim

        input = output.squeeze(1)
        source_hids = context.permute(1, 0, 2)

        x = self.linear_in(input)

        # compute attention
        attn_scores = (source_hids * x.unsqueeze(0)).sum(dim=2)

        # don't attend over padding
        attn_scores = attn_scores.float().masked_fill(mask == 0, float('-inf'))

        attn_scores = F.softmax(attn_scores, dim=0)  # srclen x bsz

        # sum weighted sources
        x = (attn_scores.unsqueeze(2) * source_hids).sum(dim=0)

        x = torch.cat((x, input), dim=1)
        x = self.linear_out(x)
        x = torch.tanh(x)

        return x, attn_scores

class Decoder(nn.Module):
    """Decoder"""
    def __init__(self, vocabulary, device,cell_name, hidden_size=512, num_layers=2,
                 max_len=500, dropout=0.5):
        super().__init__()
        self.output_dim = len(vocabulary)
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.max_length = max_len
        self.device = device
        self.eos_id = vocabulary.stoi[EOS_TOKEN]
        self.sos_id = vocabulary.stoi[SOS_TOKEN]
        self.pad_id = vocabulary.stoi[PAD_TOKEN]
        self.rnn_cell = RNN(cell_name)

        self.encoder_proj = Linear(hidden_size*2, hidden_size)

        self.embedding = Embedding(self.output_dim, self.hidden_size, self.pad_id)
        self.dropout = dropout

        self.rnn = self.rnn_cell(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=self.num_layers,
            batch_first=True,
            dropout=self.dropout if num_layers > 1 else 0.
        )

        self.attention = Attention(self.hidden_size, self.hidden_size*2, self.hidden_size)
        self.linear_out = Linear(self.hidden_size, self.output_dim)

    def _decoder_step(self, input_var, hidden, encoder_outputs, mask):
        input_var = input_var.unsqueeze(1)

        embedded = self.embedding(input_var)
        embedded = F.dropout(embedded, p=self.dropout, training=self.training)

        output, hidden = self.rnn(embedded, hidden)
        output = F.dropout(output, p=self.dropout, training=self.training)

        output, attn = self.attention(output, encoder_outputs, mask)
        output = F.dropout(output, p=self.dropout, training=self.training)

        output = self.linear_out(output)
        # output = F.dropout(output, p=self.dropout, training=self.training)
        output = F.log_softmax(output, dim=1)

        return output, hidden, attn

    def forward(self, trg_tokens, encoder_out, **kwargs):
        """
        Forward Decoder
        """
        encoder_out, hidden = encoder_out
        src_tokens = kwargs.get('src_tokens', '')
        teacher_forcing_ratio = kwargs.get('teacher_forcing_ratio', '')
        batch_size, src_length = src_tokens.size()

        if trg_tokens is None:
            teacher_forcing_ratio = 0.
            inference = True
            trg_tokens = torch.zeros((batch_size, self.max_length)).long().\
                                                                      fill_(self.sos_id).\
                                                                      to(self.device)
        else:
            inference = False

        max_length = trg_tokens.shape[1]

        outputs = torch.zeros(max_length, batch_size, self.output_dim).to(self.device)
        attentions = torch.zeros(max_length, batch_size, src_length).to(self.device)

        mask = (src_tokens != self.pad_id).t()

        # check whether encoder has lstm or gru hidden state and
        # project their output to decoder hidden state
        if isinstance(hidden, tuple):
            hidden = [self.encoder_proj(h) for h in hidden] # new_line
        else:
            hidden = self.encoder_proj(hidden)

        # use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False

        decoder_input = trg_tokens[:, 0]

        # Here we miss the output for position 0
        for i in range(1, max_length):
            output, hidden, attention = self._decoder_step(decoder_input, hidden, encoder_out, mask)
            outputs[i] = output
            attentions[i] = attention.t()
            use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False
            decoder_input = trg_tokens[:, i] if use_teacher_forcing else output.argmax(1)

            if inference and decoder_input.item() == self.eos_id and i > 0:
                return outputs[:i] # , attentions[:i]

        return outputs # , attentions