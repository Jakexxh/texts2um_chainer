import chainer
import chainer.links as L
import chainer.initializers as init
import chainer.functions as F

from scipy.spatial.distance import correlation

from src.data_util import ID_EOS


class Text2SumModel(chainer.Chain):
	
	def __init__(self, source_vocab, target_vocab, n_units):
		super(Text2SumModel, self).__init__()
		
		self.stack_depth = 2
		self.n_units = n_units
		
		with self.init_scope():
			self.encoder_embed = L.EmbedID(source_vocab, n_units)
			self.decoder_embed = L.EmbedID(target_vocab, n_units)
			self.encoder = L.NStepBiLSTM(self.stack_depth, n_units, n_units, dropout=0.5)
			self.decoder = L.NStepLSTM(self.stack_depth * 2, n_units, n_units, dropout=0.5)
			self.W = L.Linear(n_units, target_vocab)
			
	def __call__(self, encoder_input, decoder_source):
		
		batch_size = len(encoder_input)

		decoder_input = decoder_source[:, :-1]
		decoder_target = decoder_source[:, 1:]
		
		with chainer.no_backprop_mode(), chainer.using_config('train', True):
			
			encoder_inputs_emb = self.sequence_embed(self.encoder_embed,encoder_input)
			
			decoder_inputs_emb = self.sequence_embed(self.decoder_embed,decoder_input)
			
			hx, cx, _ = self.encoder(None, None, encoder_inputs_emb)
			_, _, os = self.decoder(hx, cx, decoder_inputs_emb)
			
			concat_os = F.concat(os, axis=0)
			concat_ys_out = F.concat(decoder_target, axis=0)
			loss = F.sum(F.softmax_cross_entropy(
				self.W(concat_os), concat_ys_out, reduce='no')) / batch_size
			
			chainer.report({'train_loss': loss.data}, self)
			n_words = concat_ys_out.shape[0]
			perp = self.xp.exp(loss.data * batch_size / n_words)
			chainer.report({'train_perp': perp}, self)
			
			return loss
	
	def validate(self, encoder_input, decoder_source):
		
		batch_size = len(encoder_input)
		decoder_target = decoder_source[:, 1:]
		
		with chainer.no_backprop_mode(), chainer.using_config('train', False):
			
			encoder_inputs_emb = self.sequence_embed(self.encoder_embed, encoder_input)

			decoder_input = self.xp.zeros_like(decoder_source[:, :1]) + ID_EOS
			en_h, en_c, _ = self.encoder(None, None, encoder_inputs_emb)
			
			de_h, de_c, ys = en_h, en_c, decoder_input
			result = []
			for i in range(self.xp.shape(decoder_target)[1]):
				eys = self.decoder_embed(ys)
				eys = F.split_axis(eys, batch_size, 0)
				de_h, de_c, ys = self.decoder(de_h, de_c, eys)
				cys = F.concat(ys, axis=0)
				wy = self.W(cys)
				ys = self.xp.argmax(wy.data, axis=1).astype('i')
				result.append(ys)
				
			# result = self.xp.concatenate([self.xp.expand_dims(x, 0) for x in result]).T
			result = self.xp.transpose(result)
			concat_os = F.concat(result, axis=0)
			concat_ys_out = F.concat(decoder_target, axis=0)
			loss = self.cosine_sim(concat_os.data, concat_ys_out.data) / batch_size
			chainer.report({'val_correlation': loss}, self)
			
			n_words = concat_ys_out.shape[0]
			perp = self.xp.exp(loss * batch_size / n_words)
			chainer.report({'val_perp': perp}, self)

	def sequence_embed(self, embed, xs):
		x_len = [len(x) for x in xs]
		x_section = self.xp.cumsum(x_len[:-1])
		ex = embed(F.concat(xs, axis=0))
		exs = F.split_axis(ex, x_section, 0)
		return exs
	
	def cosine_sim(self, x, y):
		
		return correlation(x + 1e-2, y + 1e-2)
