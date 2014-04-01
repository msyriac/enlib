"""This module provides classes for representing ranges of true and false values,
providing both a mask-like (numpy bool array) and list of from:to interface.
It also provides a convenience class for handling multiple of these range lists."""
import numpy as np
from enlib.slice import expand_slice, split_slice
from enlib.utils import mask2range

class Rangelist:
	def __init__(self, ranges, n=None, copy=True):
		if isinstance(ranges, Rangelist):
			if copy: ranges = ranges.copy()
			self.n, self.ranges =  ranges.n, ranges.ranges
		else:
			ranges      = np.asarray(ranges)
			if copy: ranges = np.array(ranges)
			if ranges.ndim == 1:
				self.n      = ranges.size
				self.ranges = mask2range(ranges)
			else:
				self.n      = int(n)
				self.ranges = ranges
	def __getitem__(self, sel):
		"""This function operates on the rangelist as if it were a dense numpy array.
		It returns either a sliced Rangelist or a bool."""
		if isinstance(sel,tuple):
			if len(sel) > 1: raise IndexError("Too many indices to Rangelist (only 1 supported)")
			if len(sel) == 0: return self
			sel = sel[0]
		if isinstance(sel,slice):
			sel = expand_slice(sel, self.n)
			if len(self.ranges) == 0: return self
			if (sel.stop-sel.start)*sel.step < 0: return Rangelist(np.zeros([0,2]),0)
			if sel.step > 0:
				return Rangelist(slice_helper(self.ranges, sel),(sel.stop-sel.start)/sel.step)
			else:
				res = slice_helper(self.n-self.ranges[::-1,::-1], slice(sel.stop+1, sel.start+1, -sel.step))
				return Rangelist(res, (sel.stop-sel.start)/sel.step)
		else:
			# Assume number
			i = np.searchsorted(self.ranges[:,0], sel, side="right")
			if i == 0: return False
			return self.ranges[i-1,0] <= sel and self.ranges[i-1,1] > sel
	def sum(self): return np.sum(self.ranges[:,1]-self.ranges[:,0])
	def __len__(self): return self.n
	def __repr__(self): return "Rangelist("+str(self.ranges)+",n="+repr(self.n)+")"
	def __str__(self): return repr(self)
	def copy(self): return Rangelist(self.ranges, self.n, copy=True)
	def invert(self):
		pad = np.vstack([[[0,0]],self.ranges,[[self.n,self.n]]])
		res = np.array([pad[:-1,1],pad[1:,0]]).T
		res = np.delete(res, np.where(res[:,1]==res[:,0]),0)
		return Rangelist(res, self.n)
	def to_mask(self):
		res = np.zeros(self.n,dtype=bool)
		for r1,r2 in self.ranges: res[r1:r2] = True
		return res

class Multirange:
	"""Multirange makes it easier to work with large numbers of rangelists.
	It is essentially a numpy array (though it does not expose the same
	functions) of such lists, but defines coherent slicing for both its own
	and the contained Rangelist objects indices."""
	def __init__(self, rangelists, copy=True):
		# Todo: Handle (neach, flat) inputs
		if isinstance(rangelists, Multirange):
			if copy: rangelists = rangelists.copy()
			self.data = rangelists.data
		else:
			if copy: rangelists = np.array(rangelists)
			self.data = np.asarray(rangelists)
	def __getitem__(self, sel):
		sel1, sel2 = split_slice(sel, [self.data.ndim,1])
		res = self.data[sel1]
		if isinstance(res, Rangelist): return res
		res = res.copy()
		rflat = res.reshape(res.size)
		for i in xrange(rflat.size):
			rflat[i] = rflat[i][sel2]
		if rflat.size > 0 and not isinstance(rflat[0], Rangelist):
			return res.astype(bool)
		return Multirange(res, copy=False)
	def sum(self, flat=True):
		getsum = np.vectorize(lambda x: x.sum(), 'i')
		res = getsum(self.data)
		return np.sum(res) if flat else res
	def copy(self): return Multirange(self.data, copy=True)
	def invert(self):
		return Multirange(np.vectorize(lambda x: x.invert(),'O')(self.data))
	def __repr__(self): return "Multirange("+str(self.data)+")"
	def __str__(self): return repr(self)
	def flatten(self):
		getlens = np.vectorize(lambda x: len(x.ranges), 'i')
		neach   = getlens(self.data)
		flat    = np.concatenate([r.ranges for r in self.data.reshape(self.data.size)])
		return neach, flat
	def to_mask(self):
		dflat = self.data.reshape(self.data.size)
		res   = np.zeros([dflat.size, dflat[0].n],dtype=bool)
		for i, d in enumerate(dflat):
			res[i] = d.to_mask()
		return res.reshape(self.data.shape+(-1,))

def slice_helper(ranges, sel):
	"""Helper function for rangelist slicing. Gets an expanded slice with positive
	step size."""
	if len(ranges) == 0: return ranges
	res = ranges.copy()
	# Find the first range partially ahead of this point
	i = np.searchsorted(ranges[:,1], sel.start, side="right")
	if i < len(ranges):
		res[i,0] = max(sel.start, res[i,0])
	# and similarly for the end
	j = np.searchsorted(ranges[:,0], sel.stop, side="left")
	if j > 0:
		res[j-1,1] = min(sel.stop, res[j-1,1])
	res = res[i:j]
	res -= sel.start
	# Prioritize in-range vs. out-range when reducing resolution.
	# This means that we round the lower bounds down and the upper
	# bounds up.
	res[:,0] /= sel.step
	res[:,1] = (res[:,1]+sel.step-1)/sel.step
	# Prune empty ranges
	res = res[res[:,1]-res[:,0]>0]
	return res

def multify(f):
	"""Takes any function that operates on a 1d array and a Rangelist
	and returns a function that will do the same operation on a n+1 D
	array and an N-dimensional Multirange. The inplace argument of hte
	resulting function determines whether to modify the array argument
	or not."""
	def multif(arr, multi, inplace=False, *args, **kwargs):
		kwargs["inplace"] = inplace
		if isinstance(multi, Multirange):
			mflat  = multi.data.reshape(multi.data.size)
			aflat  = arr.reshape(np.prod(arr.shape[:-1]),arr.shape[-1])
			if inplace:
				for i in range(len(aflat)):
					f(aflat[i], mflat[i], *args, **kwargs)
				return arr
			else:
				# Determine the shape of the output
				res0 = f(aflat[0].copy(), mflat[0], *args, **kwargs)
				oaflat = np.empty((aflat.shape[0],)+res0.shape)
				oaflat[0] = res0
				for i in range(1,len(aflat)):
					oaflat[i] = f(aflat[i], mflat[i], *args, **kwargs)
				return oaflat.reshape(arr.shape[:-1]+res0.shape)
		else:
			return f(arr, multi, *args, **kwargs)
	multif.__doc__ = "Multified version of function with docstring:\n" + f.__doc__
	return multif