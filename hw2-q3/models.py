import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence as pack
from torch.nn.utils.rnn import pad_packed_sequence as unpack


def reshape_state(state):
    h_state = state[0]
    c_state = state[1]
    new_h_state = torch.cat([h_state[:-1], h_state[1:]], dim=2)
    new_c_state = torch.cat([c_state[:-1], c_state[1:]], dim=2)
    return (new_h_state, new_c_state)


class BahdanauAttention(nn.Module):
    """
    Bahdanau attention mechanism:
    score(h_i, s_j) = v^T * tanh(W_h h_i + W_s s_j)
    """

    def __init__(self, hidden_size):
        super(BahdanauAttention, self).__init__()
        
        self.Ws = nn.Linear(hidden_size, hidden_size, bias=False)
        self.Wh = nn.Linear(hidden_size, hidden_size, bias=False)
        self.v = nn.Linear(hidden_size, 1, bias=False)

    def forward(self, query, encoder_outputs, src_lengths):
        """
        query:          (batch_size, max_tgt_len, hidden_size)
        encoder_outputs:(batch_size, max_src_len, hidden_size)
        src_lengths:    (batch_size)
        Returns:
            attn_out:   (batch_size, max_tgt_len, hidden_size) - attended vector
        """

        batch_size, max_src_len, hidden_size = encoder_outputs.size()
        max_tgt_len = query.size(1)

        # Prepare for storing context vectors
        context_vectors = []

        for t in range(max_tgt_len):
            # Extract the query for the current time step
            query_t = query[:, t, :]  # Shape: (batch_size, hidden_size)

            # Compute alignment scores
            scores = self.v(torch.tanh(self.Wh(encoder_outputs) + self.Ws(query_t.unsqueeze(1)))).squeeze(-1)  # (batch_size, max_src_len)

            # Apply mask to ignore padding in encoder outputs
            mask = self.sequence_mask(src_lengths)  # (batch_size, max_src_len)
            scores = scores.masked_fill(~mask, float("-inf"))

            # Normalize scores to obtain attention weights
            attention_weights = torch.softmax(scores, dim=-1)  # (batch_size, max_src_len)

            # Compute context vector as weighted sum of encoder outputs
            context_vector = torch.bmm(attention_weights.unsqueeze(1), encoder_outputs).squeeze(1)  # (batch_size, hidden_size)

            context_vectors.append(context_vector)

        # Stack context vectors for all target time steps
        context_vectors = torch.stack(context_vectors, dim=1)  # (batch_size, max_tgt_len, hidden_size)

        return context_vectors, attention_weights

    def sequence_mask(self, lengths):
        """
        Creates a boolean mask from sequence lengths.
        True for valid positions, False for padding.
        """
        batch_size = lengths.numel()
        max_len = lengths.max()
        return (torch.arange(max_len, device=lengths.device)
                .unsqueeze(0)
                .repeat(batch_size, 1)
                .lt(lengths.unsqueeze(1)))


class Encoder(nn.Module):
    def __init__(
        self,
        src_vocab_size,
        hidden_size,
        padding_idx,
        dropout,
    ):
        super(Encoder, self).__init__()
        self.hidden_size = hidden_size // 2
        self.dropout = dropout

        self.embedding = nn.Embedding(
            src_vocab_size,
            hidden_size,
            padding_idx=padding_idx,
        )
        self.lstm = nn.LSTM(
            hidden_size,
            self.hidden_size,
            bidirectional=True,
            batch_first=True,
        )
        self.dropout = nn.Dropout(self.dropout)

    def forward(
        self,
        src,
        lengths,
    ):
        # src: (batch_size, max_src_len)
        # lengths: (batch_size)
        #############################################
        # TODO: Implement the forward pass of the encoder
        # Hints:
        # - Use torch.nn.utils.rnn.pack_padded_sequence to pack the padded sequences
        #   (before passing them to the LSTM)
        # - Use torch.nn.utils.rnn.pad_packed_sequence to unpack the packed sequences
        #   (after passing them to the LSTM)
        #############################################
        
        # Embed the input tokens
        embedded = self.dropout(self.embedding(src))  # Shape: (batch_size, max_src_len, hidden_size)

        # Pack the embedded sequence
        packed = pack(embedded, lengths.cpu(), batch_first=True, enforce_sorted=False)

        # Pass through the LSTM
        packed_outputs, (hidden, cell) = self.lstm(packed)

        # Unpack the output sequence
        outputs, _ = unpack(packed_outputs, batch_first=True)  # Shape: (batch_size, max_src_len, hidden_size)

        # Apply dropout to final outputs
        outputs = self.dropout(outputs)

        return outputs, (hidden, cell)

        #############################################
        # END OF YOUR CODE
        #############################################
        # enc_output: (batch_size, max_src_len, hidden_size)
        # final_hidden: tuple with 2 tensors
        # each tensor is (num_layers * num_directions, batch_size, hidden_size)        


class Decoder(nn.Module):
    def __init__(
        self,
        hidden_size,
        tgt_vocab_size,
        attn,
        padding_idx,
        dropout,
    ):
        super(Decoder, self).__init__()
        self.hidden_size = hidden_size
        self.tgt_vocab_size = tgt_vocab_size
        self.dropout = dropout

        self.embedding = nn.Embedding(
            self.tgt_vocab_size, self.hidden_size, padding_idx=padding_idx
        )

        self.dropout = nn.Dropout(self.dropout)
        self.lstm = nn.LSTM(
            self.hidden_size,
            self.hidden_size,
            batch_first=True,
        )

        self.attn = attn

        # Initialize attention combination layer if attention is used
        if self.attn is not None:
            self.attn_combine = nn.Linear(hidden_size * 2, hidden_size)

    def forward(
        self,
        tgt,
        dec_state,
        encoder_outputs,
        src_lengths,
    ):
        # tgt: (batch_size, max_tgt_len)
        # dec_state: tuple with 2 tensors
        # each tensor is (num_layers * num_directions, batch_size, hidden_size)
        # encoder_outputs: (batch_size, max_src_len, hidden_size)
        # src_lengths: (batch_size)
        # bidirectional encoder outputs are concatenated, so we may need to
        # reshape the decoder states to be of size (num_layers, batch_size, 2*hidden_size)
        # if they are of size (num_layers*num_directions, batch_size, hidden_size)
        if dec_state[0].shape[0] == 2:
            dec_state = reshape_state(dec_state)

        #############################################
        # TODO: Implement the forward pass of the decoder
        # Hints:
        # - the input to the decoder is the previous target token,
        #   and the output is the next target token
        # - New token representations should be generated one at a time, given
        #   the previous token representation and the previous decoder state
        # - Add this somewhere in the decoder loop when you implement the attention mechanism in 3.2:
        # if self.attn is not None:
        #     output = self.attn(
        #         output,
        #         encoder_outputs,
        #         src_lengths,
        #     )
        #############################################

        # Embed the target tokens
        embedded = self.dropout(self.embedding(tgt))  # (batch_size, max_tgt_len, hidden_size)
        output, dec_state = self.lstm(embedded, dec_state)  # (batch_size, max_tgt_len, hidden_size)

        if self.attn is not None:
            context_vector, _ = self.attn(
                output, 
                encoder_outputs, 
                src_lengths
            )
            output = torch.cat((output, context_vector), dim=-1)  # (batch_size, max_tgt_len, hidden_size * 2)
            output = torch.tanh(self.attn_combine(output))  # (batch_size, max_tgt_len, hidden_size)

        output = self.dropout(output)

        return output, dec_state     

        #############################################
        # END OF YOUR CODE
        #############################################
        # outputs: (batch_size, max_tgt_len, hidden_size)
        # dec_state: tuple with 2 tensors
        # each tensor is (num_layers, batch_size, hidden_size)        


class Seq2Seq(nn.Module):
    def __init__(
        self,
        encoder,
        decoder,
    ):
        super(Seq2Seq, self).__init__()

        self.encoder = encoder
        self.decoder = decoder

        self.generator = nn.Linear(decoder.hidden_size, decoder.tgt_vocab_size)

        self.generator.weight = self.decoder.embedding.weight

    def forward(
        self,
        src,
        src_lengths,
        tgt,
        dec_hidden=None,
    ):

        encoder_outputs, final_enc_state = self.encoder(src, src_lengths)

        if dec_hidden is None:
            dec_hidden = final_enc_state

        output, dec_hidden = self.decoder(
            tgt, dec_hidden, encoder_outputs, src_lengths
        )

        return self.generator(output), dec_hidden
