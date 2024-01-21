import math

import torch
from torch import nn
from torch.nn import functional as F

from TTS.tts.utils.helpers import sequence_mask
from TTS.tts.layers.generic.normalization import LayerNorm, LayerNorm2

class AdaptiveWeightConv(nn.Module):
    def __init__(self, conv_module, in_channels, out_channels, kernel_size, r=0, alpha=1, dropout=0., num_classes=None, **kwargs):
        super(AdaptiveWeightConv, self).__init__()
        self.conv = conv_module(in_channels, out_channels, kernel_size, **kwargs)
        self.r = r

        # it is only support when kernel_size is equal to 1
        if kernel_size != 1:
            self.r = 0

        self.alpha = alpha
        self.num_classes = num_classes

        self.weight = self.conv.weight
        # Optional dropout
        if dropout > 0.:
            self.dropout = nn.Dropout(p=dropout)
        else:
            self.dropout = lambda x: x

        assert isinstance(kernel_size, int)
        # Actual trainable parameters
        if self.r > 0:
            # create layers for each class

            # self.W_Ms = nn.Parameter(
            #     self.conv.weight.new_zeros((r * kernel_size, in_channels * kernel_size))
            # )

            # self.W_Bs = nn.Parameter(
            #   self.conv.weight.new_zeros((out_channels//self.conv.groups*kernel_size, r*kernel_size))
            # )
            W_Ms_layers = [nn.Parameter(self.conv.weight.new_zeros((r * kernel_size, in_channels * kernel_size))) for _ in range(0, num_classes)]
            self.W_Ms = nn.ParameterList(W_Ms_layers)
            W_Bs_layers = [nn.Parameter(self.conv.weight.new_zeros((out_channels//self.conv.groups*kernel_size, r*kernel_size))) for _ in range(0, num_classes)]
            self.W_Bs = nn.ParameterList(W_Bs_layers)

            # self.m_shape = (r * kernel_size, in_channels * kernel_size)
            # self.W_Ms = nn.Embedding(num_classes, self.m_shape[0] * self.m_shape[1])
            # self.b_shape = (out_channels//self.conv.groups*kernel_size, r*kernel_size)
            # self.W_Bs = nn.Embedding(num_classes, self.b_shape[0] * self.b_shape[1])
            self.scaling = self.alpha / self.r
        self.reset_parameters()

    def reset_parameters(self):
        self.conv.reset_parameters()
        if hasattr(self, 'W_Ms'):
            # initialize A the same way as the default for nn.Linear and B to zero
            
            # nn.init.kaiming_uniform_(self.W_Ms, a=math.sqrt(5))
            # nn.init.zeros_(self.W_Bs)

            for i in range(0, self.num_classes):
                nn.init.kaiming_uniform_(self.W_Ms[i], a=math.sqrt(5))
                nn.init.zeros_(self.W_Bs[i])
            
            # nn.init.kaiming_uniform_(self.W_Ms.weight, a=math.sqrt(5))
            # nn.init.zeros_(self.W_Bs.weight)

    def train(self, mode=True):
        super(AdaptiveWeightConv, self).train(mode)

    def forward(self, x, class_id=None):
        if self.r > 0:
            # W_M_layer = self.W_Ms(class_ids).view(class_ids.size(0), *self.m_shape)
            # W_B_layer = self.W_Bs(class_ids).view(class_ids.size(0), *self.b_shape)
            W_M_layer = self.W_Ms[class_id]
            W_B_layer = self.W_Bs[class_id]
            # W_M_layer = self.W_Ms
            # W_B_layer = self.W_Bs

            # print(self.conv.weight.shape, (W_B_layer @ W_M_layer).shape, W_M_layer.shape, W_B_layer.shape)
            return self.conv._conv_forward(
                x, 
                self.conv.weight + (W_B_layer @ W_M_layer).view(self.conv.weight.shape) * self.scaling,
                self.conv.bias
            )
        return self.conv(x)

class Conv2d(AdaptiveWeightConv):
    def __init__(self, *args, **kwargs):
        super(Conv2d, self).__init__(nn.Conv2d, *args, **kwargs)

class Conv1d(AdaptiveWeightConv):
    def __init__(self, *args, **kwargs):
        super(Conv1d, self).__init__(nn.Conv1d, *args, **kwargs)

# Can Extend to other ones like this

class Conv3d(AdaptiveWeightConv):
    def __init__(self, *args, **kwargs):
        super(Conv3d, self).__init__(nn.Conv3d, *args, **kwargs)


class RelativePositionMultiHeadAttention(nn.Module):
    """Multi-head attention with Relative Positional embedding.
    https://arxiv.org/pdf/1809.04281.pdf

    It learns positional embeddings for a window of neighbours. For keys and values,
    it learns different set of embeddings. Key embeddings are agregated with the attention
    scores and value embeddings are aggregated with the output.

    Note:
        Example with relative attention window size 2

        - input = [a, b, c, d, e]
        - rel_attn_embeddings = [e(t-2), e(t-1), e(t+1), e(t+2)]

        So it learns 4 embedding vectors (in total 8) separately for key and value vectors.

        Considering the input c

        - e(t-2) corresponds to c -> a
        - e(t-2) corresponds to c -> b
        - e(t-2) corresponds to c -> d
        - e(t-2) corresponds to c -> e

        These embeddings are shared among different time steps. So input a, b, d and e also uses
        the same embeddings.

        Embeddings are ignored when the relative window is out of limit for the first and the last
        n items.

    Args:
        channels (int): input and inner layer channels.
        out_channels (int): output channels.
        num_heads (int): number of attention heads.
        rel_attn_window_size (int, optional): relation attention window size.
            If 4, for each time step next and previous 4 time steps are attended.
            If default, relative encoding is disabled and it is a regular transformer.
            Defaults to None.
        heads_share (bool, optional): [description]. Defaults to True.
        dropout_p (float, optional): dropout rate. Defaults to 0..
        input_length (int, optional): intput length for positional encoding. Defaults to None.
        proximal_bias (bool, optional): enable/disable proximal bias as in the paper. Defaults to False.
        proximal_init (bool, optional): enable/disable poximal init as in the paper.
            Init key and query layer weights the same. Defaults to False.
    """

    def __init__(
        self,
        channels,
        out_channels,
        num_heads,
        rel_attn_window_size=None,
        heads_share=True,
        dropout_p=0.0,
        input_length=None,
        proximal_bias=False,
        proximal_init=False,
        num_adaptive_weight_classes=None,
    ):
        super().__init__()
        assert channels % num_heads == 0, " [!] channels should be divisible by num_heads."
        # class attributes
        self.channels = channels
        self.out_channels = out_channels
        self.num_heads = num_heads
        self.rel_attn_window_size = rel_attn_window_size
        self.heads_share = heads_share
        self.input_length = input_length
        self.proximal_bias = proximal_bias
        self.dropout_p = dropout_p
        self.attn = None
        # query, key, value layers
        self.k_channels = channels // num_heads
        self.conv_q = Conv1d(channels, channels, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        self.conv_k = Conv1d(channels, channels, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        self.conv_v = Conv1d(channels, channels, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        # output layers
        self.conv_o = Conv1d(channels, out_channels, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        self.dropout = nn.Dropout(dropout_p)
        # relative positional encoding layers
        if rel_attn_window_size is not None:
            n_heads_rel = 1 if heads_share else num_heads
            rel_stddev = self.k_channels**-0.5
            emb_rel_k = nn.Parameter(
                torch.randn(n_heads_rel, rel_attn_window_size * 2 + 1, self.k_channels) * rel_stddev
            )
            emb_rel_v = nn.Parameter(
                torch.randn(n_heads_rel, rel_attn_window_size * 2 + 1, self.k_channels) * rel_stddev
            )
            self.register_parameter("emb_rel_k", emb_rel_k)
            self.register_parameter("emb_rel_v", emb_rel_v)

        # init layers
        nn.init.xavier_uniform_(self.conv_q.weight)
        nn.init.xavier_uniform_(self.conv_k.weight)
        # proximal bias
        if proximal_init:
            self.conv_k.weight.data.copy_(self.conv_q.weight.data)
            self.conv_k.bias.data.copy_(self.conv_q.bias.data)
        nn.init.xavier_uniform_(self.conv_v.weight)

    def forward(self, x, c, attn_mask=None, class_id=None):
        """
        Shapes:
            - x: :math:`[B, C, T]`
            - c: :math:`[B, C, T]`
            - attn_mask: :math:`[B, 1, T, T]`
        """
        q = self.conv_q(x, class_id=class_id)
        k = self.conv_k(c, class_id=class_id)
        v = self.conv_v(c, class_id=class_id)
        x, self.attn = self.attention(q, k, v, mask=attn_mask)
        x = self.conv_o(x, class_id=class_id)
        return x

    def attention(self, query, key, value, mask=None):
        # reshape [b, d, t] -> [b, n_h, t, d_k]
        b, d, t_s, t_t = (*key.size(), query.size(2))
        query = query.view(b, self.num_heads, self.k_channels, t_t).transpose(2, 3)
        key = key.view(b, self.num_heads, self.k_channels, t_s).transpose(2, 3)
        value = value.view(b, self.num_heads, self.k_channels, t_s).transpose(2, 3)
        # compute raw attention scores
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.k_channels)
        # relative positional encoding for scores
        if self.rel_attn_window_size is not None:
            assert t_s == t_t, "Relative attention is only available for self-attention."
            # get relative key embeddings
            key_relative_embeddings = self._get_relative_embeddings(self.emb_rel_k, t_s)
            rel_logits = self._matmul_with_relative_keys(query, key_relative_embeddings)
            rel_logits = self._relative_position_to_absolute_position(rel_logits)
            scores_local = rel_logits / math.sqrt(self.k_channels)
            scores = scores + scores_local
        # proximan bias
        if self.proximal_bias:
            assert t_s == t_t, "Proximal bias is only available for self-attention."
            scores = scores + self._attn_proximity_bias(t_s).to(device=scores.device, dtype=scores.dtype)
        # attention score masking
        if mask is not None:
            # add small value to prevent oor error.
            scores = scores.masked_fill(mask == 0, -1e4)
            if self.input_length is not None:
                block_mask = torch.ones_like(scores).triu(-1 * self.input_length).tril(self.input_length)
                scores = scores * block_mask + -1e4 * (1 - block_mask)
        # attention score normalization
        p_attn = F.softmax(scores, dim=-1)  # [b, n_h, t_t, t_s]
        # apply dropout to attention weights
        p_attn = self.dropout(p_attn)
        # compute output
        output = torch.matmul(p_attn, value)
        # relative positional encoding for values
        if self.rel_attn_window_size is not None:
            relative_weights = self._absolute_position_to_relative_position(p_attn)
            value_relative_embeddings = self._get_relative_embeddings(self.emb_rel_v, t_s)
            output = output + self._matmul_with_relative_values(relative_weights, value_relative_embeddings)
        output = output.transpose(2, 3).contiguous().view(b, d, t_t)  # [b, n_h, t_t, d_k] -> [b, d, t_t]
        return output, p_attn

    @staticmethod
    def _matmul_with_relative_values(p_attn, re):
        """
        Args:
            p_attn (Tensor): attention weights.
            re (Tensor): relative value embedding vector. (a_(i,j)^V)

        Shapes:
            -p_attn: :math:`[B, H, T, V]`
            -re: :math:`[H or 1, V, D]`
            -logits: :math:`[B, H, T, D]`
        """
        logits = torch.matmul(p_attn, re.unsqueeze(0))
        return logits

    @staticmethod
    def _matmul_with_relative_keys(query, re):
        """
        Args:
            query (Tensor): batch of query vectors. (x*W^Q)
            re (Tensor): relative key embedding vector. (a_(i,j)^K)

        Shapes:
            - query: :math:`[B, H, T, D]`
            - re: :math:`[H or 1, V, D]`
            - logits: :math:`[B, H, T, V]`
        """
        # logits = torch.einsum('bhld, kmd -> bhlm', [query, re.to(query.dtype)])
        logits = torch.matmul(query, re.unsqueeze(0).transpose(-2, -1))
        return logits

    def _get_relative_embeddings(self, relative_embeddings, length):
        """Convert embedding vestors to a tensor of embeddings"""
        # Pad first before slice to avoid using cond ops.
        pad_length = max(length - (self.rel_attn_window_size + 1), 0)
        slice_start_position = max((self.rel_attn_window_size + 1) - length, 0)
        slice_end_position = slice_start_position + 2 * length - 1
        if pad_length > 0:
            padded_relative_embeddings = F.pad(relative_embeddings, [0, 0, pad_length, pad_length, 0, 0])
        else:
            padded_relative_embeddings = relative_embeddings
        used_relative_embeddings = padded_relative_embeddings[:, slice_start_position:slice_end_position]
        return used_relative_embeddings

    @staticmethod
    def _relative_position_to_absolute_position(x):
        """Converts tensor from relative to absolute indexing for local attention.
        Shapes:
            x: :math:`[B, C, T, 2 * T - 1]`
        Returns:
            A Tensor of shape :math:`[B, C, T, T]`
        """
        batch, heads, length, _ = x.size()
        # Pad to shift from relative to absolute indexing.
        x = F.pad(x, [0, 1, 0, 0, 0, 0, 0, 0])
        # Pad extra elements so to add up to shape (len+1, 2*len-1).
        x_flat = x.view([batch, heads, length * 2 * length])
        x_flat = F.pad(x_flat, [0, length - 1, 0, 0, 0, 0])
        # Reshape and slice out the padded elements.
        x_final = x_flat.view([batch, heads, length + 1, 2 * length - 1])[:, :, :length, length - 1 :]
        return x_final

    @staticmethod
    def _absolute_position_to_relative_position(x):
        """
        Shapes:
            - x: :math:`[B, C, T, T]`
            - ret: :math:`[B, C, T, 2*T-1]`
        """
        batch, heads, length, _ = x.size()
        # padd along column
        x = F.pad(x, [0, length - 1, 0, 0, 0, 0, 0, 0])
        x_flat = x.view([batch, heads, length**2 + length * (length - 1)])
        # add 0's in the beginning that will skew the elements after reshape
        x_flat = F.pad(x_flat, [length, 0, 0, 0, 0, 0])
        x_final = x_flat.view([batch, heads, length, 2 * length])[:, :, :, 1:]
        return x_final

    @staticmethod
    def _attn_proximity_bias(length):
        """Produce an attention mask that discourages distant
        attention values.
        Args:
            length (int): an integer scalar.
        Returns:
            a Tensor with shape :math:`[1, 1, T, T]`
        """
        # L
        r = torch.arange(length, dtype=torch.float32)
        # L x L
        diff = torch.unsqueeze(r, 0) - torch.unsqueeze(r, 1)
        # scale mask values
        diff = -torch.log1p(torch.abs(diff))
        # 1 x 1 x L x L
        return diff.unsqueeze(0).unsqueeze(0)


class FeedForwardNetwork(nn.Module):
    """Feed Forward Inner layers for Transformer.

    Args:
        in_channels (int): input tensor channels.
        out_channels (int): output tensor channels.
        hidden_channels (int): inner layers hidden channels.
        kernel_size (int): conv1d filter kernel size.
        dropout_p (float, optional): dropout rate. Defaults to 0.
    """
    def __init__(self, in_channels, out_channels, hidden_channels, kernel_size, dropout_p=0.0, causal=False, num_adaptive_weight_classes=None):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.hidden_channels = hidden_channels
        self.kernel_size = kernel_size
        self.dropout_p = dropout_p

        if causal:
            self.padding = self._causal_padding
        else:
            self.padding = self._same_padding

        self.conv_1 = Conv1d(in_channels, hidden_channels, kernel_size, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        self.conv_2 = Conv1d(hidden_channels, out_channels, kernel_size, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)
        self.dropout = nn.Dropout(dropout_p)

    def forward(self, x, x_mask, class_id=None):
        x = self.conv_1(self.padding(x * x_mask), class_id=class_id)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.conv_2(self.padding(x * x_mask), class_id=class_id)
        return x * x_mask

    def _causal_padding(self, x):
        if self.kernel_size == 1:
            return x
        pad_l = self.kernel_size - 1
        pad_r = 0
        padding = [[0, 0], [0, 0], [pad_l, pad_r]]
        x = F.pad(x, self._pad_shape(padding))
        return x

    def _same_padding(self, x):
        if self.kernel_size == 1:
            return x
        pad_l = (self.kernel_size - 1) // 2
        pad_r = self.kernel_size // 2
        padding = [[0, 0], [0, 0], [pad_l, pad_r]]
        x = F.pad(x, self._pad_shape(padding))
        return x

    @staticmethod
    def _pad_shape(padding):
        l = padding[::-1]
        pad_shape = [item for sublist in l for item in sublist]
        return pad_shape


class RelativePositionTransformer(nn.Module):
    """Transformer with Relative Potional Encoding.
    https://arxiv.org/abs/1803.02155

    Args:
        in_channels (int): number of channels of the input tensor.
        out_chanels (int): number of channels of the output tensor.
        hidden_channels (int): model hidden channels.
        hidden_channels_ffn (int): hidden channels of FeedForwardNetwork.
        num_heads (int): number of attention heads.
        num_layers (int): number of transformer layers.
        kernel_size (int, optional): kernel size of feed-forward inner layers. Defaults to 1.
        dropout_p (float, optional): dropout rate for self-attention and feed-forward inner layers_per_stack. Defaults to 0.
        rel_attn_window_size (int, optional): relation attention window size.
            If 4, for each time step next and previous 4 time steps are attended.
            If default, relative encoding is disabled and it is a regular transformer.
            Defaults to None.
        input_length (int, optional): input lenght to limit position encoding. Defaults to None.
        layer_norm_type (str, optional): type "1" uses torch tensor operations and type "2" uses torch layer_norm
            primitive. Use type "2", type "1: is for backward compat. Defaults to "1".
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        hidden_channels: int,
        hidden_channels_ffn: int,
        num_heads: int,
        num_layers: int,
        kernel_size=1,
        dropout_p=0.0,
        rel_attn_window_size: int = None,
        input_length: int = None,
        layer_norm_type: str = "1",
        num_adaptive_weight_classes: int = None,
    ):
        super().__init__()
        self.hidden_channels = hidden_channels
        self.hidden_channels_ffn = hidden_channels_ffn
        self.num_heads = num_heads
        self.num_layers = num_layers
        self.kernel_size = kernel_size
        self.dropout_p = dropout_p
        self.rel_attn_window_size = rel_attn_window_size

        self.dropout = nn.Dropout(dropout_p)
        self.attn_layers = nn.ModuleList()
        self.norm_layers_1 = nn.ModuleList()
        self.ffn_layers = nn.ModuleList()
        self.norm_layers_2 = nn.ModuleList()

        for idx in range(self.num_layers):
            self.attn_layers.append(
                RelativePositionMultiHeadAttention(
                    hidden_channels if idx != 0 else in_channels,
                    hidden_channels,
                    num_heads,
                    rel_attn_window_size=rel_attn_window_size,
                    dropout_p=dropout_p,
                    input_length=input_length,
                    num_adaptive_weight_classes=num_adaptive_weight_classes,
                )
            )
            if layer_norm_type == "1":
                self.norm_layers_1.append(LayerNorm(hidden_channels))
            elif layer_norm_type == "2":
                self.norm_layers_1.append(LayerNorm2(hidden_channels))
            else:
                raise ValueError(" [!] Unknown layer norm type")

            if hidden_channels != out_channels and (idx + 1) == self.num_layers:
                self.proj = Conv1d(hidden_channels, out_channels, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)

            self.ffn_layers.append(
                FeedForwardNetwork(
                    hidden_channels,
                    hidden_channels if (idx + 1) != self.num_layers else out_channels,
                    hidden_channels_ffn,
                    kernel_size,
                    dropout_p=dropout_p,
                    num_adaptive_weight_classes=num_adaptive_weight_classes,
                )
            )

            if layer_norm_type == "1":
                self.norm_layers_2.append(LayerNorm(hidden_channels if (idx + 1) != self.num_layers else out_channels))
            elif layer_norm_type == "2":
                self.norm_layers_2.append(LayerNorm2(hidden_channels if (idx + 1) != self.num_layers else out_channels))
            else:
                raise ValueError(" [!] Unknown layer norm type")

    def forward(self, x, x_mask, class_id=None):
        """
        Shapes:
            - x: :math:`[B, C, T]`
            - x_mask: :math:`[B, 1, T]`
        """
        attn_mask = x_mask.unsqueeze(2) * x_mask.unsqueeze(-1)
        for i in range(self.num_layers):
            x = x * x_mask
            y = self.attn_layers[i](x, x, attn_mask, class_id=class_id)
            y = self.dropout(y)
            x = self.norm_layers_1[i](x + y)

            y = self.ffn_layers[i](x, x_mask, class_id=class_id)
            y = self.dropout(y)

            if (i + 1) == self.num_layers and hasattr(self, "proj"):
                x = self.proj(x, class_id=class_id)

            x = self.norm_layers_2[i](x + y)
        x = x * x_mask
        return x

class TextEncoder(nn.Module):
    def __init__(
        self,
        n_vocab: int,
        out_channels: int,
        hidden_channels: int,
        hidden_channels_ffn: int,
        num_heads: int,
        num_layers: int,
        kernel_size: int,
        dropout_p: float,
        language_emb_dim: int = None,
        num_adaptive_weight_classes: int = None,
    ):
        """Text Encoder for VITS model.

        Args:
            n_vocab (int): Number of characters for the embedding layer.
            out_channels (int): Number of channels for the output.
            hidden_channels (int): Number of channels for the hidden layers.
            hidden_channels_ffn (int): Number of channels for the convolutional layers.
            num_heads (int): Number of attention heads for the Transformer layers.
            num_layers (int): Number of Transformer layers.
            kernel_size (int): Kernel size for the FFN layers in Transformer network.
            dropout_p (float): Dropout rate for the Transformer layers.
        """
        super().__init__()
        self.out_channels = out_channels
        self.hidden_channels = hidden_channels
        self.num_adaptive_weight_classes = num_adaptive_weight_classes
        self.emb = nn.Embedding(n_vocab, hidden_channels)

        nn.init.normal_(self.emb.weight, 0.0, hidden_channels**-0.5)

        if language_emb_dim:
            hidden_channels += language_emb_dim

        self.encoder = RelativePositionTransformer(
            in_channels=hidden_channels,
            out_channels=hidden_channels,
            hidden_channels=hidden_channels,
            hidden_channels_ffn=hidden_channels_ffn,
            num_heads=num_heads,
            num_layers=num_layers,
            kernel_size=kernel_size,
            dropout_p=dropout_p,
            layer_norm_type="2",
            rel_attn_window_size=4,
            num_adaptive_weight_classes=num_adaptive_weight_classes,
        )

        self.proj = Conv1d(hidden_channels, out_channels * 2, 1, r=1 if num_adaptive_weight_classes else 0, num_classes=num_adaptive_weight_classes)

    def forward_mini_batch(self, x, x_lengths, lang_emb=None, class_id=None):
        assert x.shape[0] == x_lengths.shape[0]
        x = self.emb(x) * math.sqrt(self.hidden_channels)  # [b, t, h]

        # concat the lang emb in embedding chars
        if lang_emb is not None:
            x = torch.cat((x, lang_emb.transpose(2, 1).expand(x.size(0), x.size(1), -1)), dim=-1)

        x = torch.transpose(x, 1, -1)  # [b, h, t]
        x_mask = torch.unsqueeze(sequence_mask(x_lengths, x.size(2)), 1).to(x.dtype)  # [b, 1, t]

        x = self.encoder(x * x_mask, x_mask, class_id=class_id)
        stats = self.proj(x, class_id=class_id) * x_mask

        m, logs = torch.split(stats, self.out_channels, dim=1)
        return x, m, logs, x_mask

    def forward(self, x, x_lengths, lang_emb=None, class_id=None):
        """
        Shapes:
            - x: :math:`[B, T]`
            - x_length: :math:`[B]`
        """
        batch_size = x.size(0)
        if self.num_adaptive_weight_classes and batch_size > 1:
            num_utter_per_class = int(batch_size/self.num_adaptive_weight_classes)
            # mini batch inference for each class
            outs_x = []
            outs_m = [] 
            outs_logs = []
            outs_x_mask = []

            start = 0
            for i in range(self.num_adaptive_weight_classes):
                start = num_utter_per_class * i
                end = start + num_utter_per_class
                class_id_item = class_id[start:end][0]
                x_out, m_out, logs_out, x_mask_out = self.forward_mini_batch(x[start:end], x_lengths[start:end], lang_emb=lang_emb[start:end] if lang_emb else None, class_id=class_id_item)
                outs_x.append(x_out)
                outs_m.append(m_out)
                outs_logs.append(logs_out)
                outs_x_mask.append(x_mask_out)

            x = torch.stack(outs_x, dim=0).view(batch_size, *x_out.shape[1:])
            m = torch.stack(outs_m, dim=0).view(batch_size, *m_out.shape[1:])
            logs = torch.stack(outs_logs, dim=0).view(batch_size, *logs_out.shape[1:])
            x_mask = torch.stack(outs_x_mask, dim=0).view(batch_size, *x_mask_out.shape[1:])
            return x, m, logs, x_mask
        else:
            return self.forward_mini_batch(x, x_lengths, lang_emb=lang_emb, class_id=class_id)


if __name__ == '__main__':
    txt_enc = TextEncoder(
        n_vocab=100,
        out_channels=192,
        hidden_channels=192,
        hidden_channels_ffn=80,
        num_heads=2,
        num_layers=1,
        kernel_size=3,
        dropout_p=0.0,
        language_emb_dim=None,
        num_adaptive_weight_classes=5,
    )

    B = 3
    T = 50
    x = torch.ones(B, 100).long()
    x_lengths = torch.ones(B).long()
    x_lengths[0]=50
    class_id = 1

    out = txt_enc(
        x,
        x_lengths,
        class_id=class_id
    )
    print("With adaptive Weights:",out[0].shape)

    txt_enc = TextEncoder(
        n_vocab=100,
        out_channels=192,
        hidden_channels=192,
        hidden_channels_ffn=80,
        num_heads=2,
        num_layers=1,
        kernel_size=3,
        dropout_p=0.0,
        language_emb_dim=None,
        num_adaptive_weight_classes=None,
    )

    out = txt_enc(
        x,
        x_lengths,
        class_id=class_id
    )
    print("Without adaptive Weights:",out[0].shape)