import numpy as np, fortran_32, fortran_64
from .. import fft, utils, coordinates

def get_core(dtype):
	if dtype == np.float32:
		return fortran_32.fortran
	elif dtype == np.float64:
		return fortran_64.fortran
	raise NotImplementedError

def nmat_mwhite(tod, noise, submean=2):
	"""Applies white noise + mean subtraction noise model to tod, overwriting it."""
	core = get_core(tod.dtype)
	rangemask = np.zeros(noise.ranges.shape[0],dtype=np.int32)+1
	core.nmat_mwhite(tod, noise.ranges.T, noise.rangesets, noise.offsets.T, noise.ivars, submean, rangemask)
	return tod

def measure_mwhite(tod, data, submean=2):
	core = get_core(tod.dtype)
	nsrc, ndet = data.offsets.shape[:2]
	vars  = np.zeros([nsrc,ndet],dtype=tod.dtype)
	nvars = np.zeros([nsrc,ndet],dtype=np.int32)
	core.measure_mwhite(tod, data.ranges.T, data.rangesets, data.offsets.T, vars.T, nvars.T, submean)
	return vars, nvars

def nmat_basis(tod, noise, white=False):
	core = get_core(tod.dtype)
	rangemask = np.zeros(noise.ranges.shape[0],dtype=np.int32)+1
	Q = noise.Q
	if white: Q = Q*0
	core.nmat_basis(tod, noise.ranges.T, noise.rangesets, noise.offsets.T, noise.ivars, Q.T, rangemask)
	return tod

def measure_basis(tod, data):
	core = get_core(tod.dtype)
	nsrc, ndet = data.offsets.shape[:2]
	vars  = np.zeros([nsrc,ndet],dtype=tod.dtype)
	nvars = np.zeros([nsrc,ndet],dtype=np.int32)
	core.measure_basis(tod, data.ranges.T, data.rangesets, data.offsets.T, vars.T, nvars.T, data.Q.T)
	return vars, nvars

def build_noise_basis(data, nbasis, minorder=2):
	nmax = np.max(data.ranges[:,1]-data.ranges[:,0])
	nb = nbasis if nbasis >= 0 else max(minorder,(nmax-nbasis-1)/(-nbasis))
	Q = np.zeros((data.tod.size,max(1,nb)))
	if nbasis == 0: return Q
	lendb = {}
	for r in data.ranges:
		n = r[1]-r[0]
		if n == 0:
			continue
		if n in lendb:
			i = lendb[n]
			Q[r[0]:r[1],:] = Q[i:i+r[1]-r[0],:]
		else:
			if n == 1:
				Q[r[0]:r[1],:] = 0
			else:
				# Cap number of basis vectors to [minorder:n]
				nvec = nbasis if nbasis >= 0 else min(n,max(minorder,(n-nbasis-1)/(-nbasis)))
				# Build the first nbasis chebyshev polynomials
				V = fft.chebt(np.eye(n)[:nvec]).T
				# We want QQ' = V(V'V)"V', so Q = V(V'V)**-0.5
				Qr = V.dot(np.linalg.cholesky(np.linalg.inv(V.T.dot(V))))
				# Confirm that QrQr' = V(V'V)"V'
				Q[r[0]:r[1],:nvec] = Qr
			lendb[n] = r[0]
	return Q

def build_noise_basis_adaptive(data, nmin=2, nmax=20, lim=2):
	"""Build a polynomial noise basis per sample range based on
	a simple f_knee detection."""
	Q = np.zeros((data.tod.size,nmax))
	for r in data.ranges:
		n = r[1]-r[0]
		if n < 2: continue
		ps = np.abs(np.fft.rfft(data.tod[r[0]:r[1]]))**2
		if len(ps) < 2: nbad = 1
		else:
			ps /= np.median(ps[len(ps)/2:])
			nbad = np.where(ps<=lim)[0][0]
		nvec = max(nmin,min(nbad, nmax))
		# Build the first nbasis chebyshev polynomials
		V = fft.chebt(np.eye(n)[:nvec]).T
		# We want QQ' = V(V'V)"V', so Q = V(V'V)**-0.5
		Qr = V.dot(np.linalg.cholesky(np.linalg.inv(V.T.dot(V))))
		# Confirm that QrQr' = V(V'V)"V'
		Q[r[0]:r[1],:nvec] = Qr
	return Q

def pmat_thumbs(dir, tod, maps, point, phase, boxes):
	core = get_core(tod.dtype)
	core.pmat_thumbs(dir, tod.T, maps.T, point.T, phase.T, boxes.T)

def pmat_thumbs_hor(dir, tod, maps, point, phase, boxes, rbox, nbox, ys):
	core = get_core(tod.dtype)
	core.pmat_thumbs_hor(dir, tod.T, maps.T, point.T, phase.T, boxes.T, rbox.T, nbox, ys.T)

def pmat_model(tod, params, data, dir=1):
	core = get_core(tod.dtype)
	rangemask = np.zeros(data.ranges.shape[0],dtype=np.int32)+1
	# Make sure the point sources are on the same side of the angle cut.
	# NB: This function uses the transpose params compared to PmatPtsrc.
	# That should be fixed.
	p = params.copy()
	p[:,:2] = utils.rewind(params[:,:2], data.point[0])
	core.pmat_model(dir, tod, p.T, data.ranges.T, data.rangesets.T, data.offsets.T, data.point.T, data.phase.T, rangemask)
	params[:,2:-3] = p[:,2:-3]

def pmat_beam_foff(tod, params, beam, data, dir=1):
	core = get_core(tod.dtype)
	p = params.copy()
	p[:,:2] = utils.rewind(params[:,:2], data.point[0,-2:])
	# Apply focal-plane offset to our base offsets, and convert to horizontal offsets
	mean_point   = np.mean(data.point[:,1:],0)
	point_offset = data.point_offset + params[None,0,8:]
	point_offset = coordinates.decenter(point_offset.T, np.concatenate([mean_point,mean_point*0])).T - mean_point[None]
	point_offset = np.concatenate([point_offset[:,:1]*0,point_offset],1)
	core.pmat_beam_foff(dir, tod, p.T, data.ranges.T, data.rangesets.T, data.offsets.T,
			data.point.T, point_offset.T, data.phase.T, data.rbox.T, data.nbox, data.ys.T, beam.profile, beam.rmax)
	params[:,2:-3] = p[:,2:-3]

def chisq_by_range(tod, params, data, prev_params=None, prev_chisqs=None):
	changed = np.zeros(params.shape,dtype=bool)+True if prev_params is None else params != prev_params
	if not np.any(changed): return prev_chisqs
	# Make sure the point sources are on the same side of the angle cut.
	params = params.copy()
	params[:,:2] = utils.rewind(params[:,:2], data.point[0])
	# Check which sources have changed
	core = get_core(tod.dtype)
	changed_srcs   = np.any(changed,axis=1).astype(np.int32)
	changed_ranges = np.zeros(data.ranges.shape[0],np.int32)
	core.srcmask2rangemask(changed_srcs, data.rangesets.T, data.offsets.T, changed_ranges)
	# Compute the chisquare for the changed ranges
	wtod = np.empty(tod.shape, tod.dtype)
	core.pmat_model(1, wtod, params.T, data.ranges.T, data.rangesets.T, data.offsets.T, data.point.T, data.phase.T, changed_ranges)
	core.rangesub(wtod, tod, data.ranges.T, changed_ranges)
	ntod = wtod.copy()
	core.nmat_basis(ntod, data.ranges.T, data.rangesets.T, data.offsets.T, data.ivars, data.Q.T, changed_ranges)
	chisqs = np.zeros(data.ranges.shape[0],dtype=np.float64)
	core.rangechisq(wtod, ntod, data.ranges.T, chisqs, changed_ranges)
	# Fill in old chisquares for those that didn't change
	if prev_params is not None:
		chisqs[changed_ranges==0] = prev_chisqs[changed_ranges==0]
	return chisqs

def chisq(tod, params, data):
	core = get_core(tod.dtype)
	wtod = np.empty(tod.shape, tod.dtype)
	pmat_model(wtod, params, data)
	wtod -= tod
	ntod = wtod.copy()
	nmat_basis(ntod, data)
	return np.sum(wtod*ntod)
