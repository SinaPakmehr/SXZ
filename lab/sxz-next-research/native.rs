use std::slice::{from_raw_parts, from_raw_parts_mut};

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Hit {
    pos: u32, len: u32, a: u32, b: u32, c: u32, x: u32, y: u32,
}

fn word(s: &[u8], i: usize) -> u32 {
    u32::from_le_bytes(s[i..i+4].try_into().unwrap())
}

fn inverse_odd(x: u32) -> u32 {
    let mut y = 1u32;
    for _ in 0..5 { y = y.wrapping_mul(2u32.wrapping_sub(x.wrapping_mul(y))); }
    y
}

fn prediction(a: u32, b: u32, c: u32, x: u32, y: u32) -> u32 {
    a.wrapping_mul(y).wrapping_add(b.wrapping_mul(x)).wrapping_add(c)
}

// All byte phases; one fit and one shared verification for the 12 dyadic windows.
// Pass byte pointers and correctly sized disjoint output buffers to these C ABIs.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn scan(src: *const u8, n: usize, dst: *mut Hit, cap: usize,
                             step: usize, min_span: usize) -> usize {
    if n > u32::MAX as usize || step == 0 || !(32..=65536).contains(&min_span) { return 0; }
    let s = unsafe { from_raw_parts(src, n) };
    let output = unsafe { from_raw_parts_mut(dst, cap) };
    let mut pos = 0;
    let mut found = 0;
    while pos + min_span <= n {
        let (x, y, z, t, u) = (word(s,pos), word(s,pos+4), word(s,pos+8), word(s,pos+12), word(s,pos+16));
        let (d0,d1,d2,d3) = (y.wrapping_sub(x),z.wrapping_sub(y),t.wrapping_sub(z),u.wrapping_sub(t));
        let det = d1.wrapping_mul(d1).wrapping_sub(d2.wrapping_mul(d0));
        if det & 1 != 0 {
            let inv = inverse_odd(det);
            let a = inv.wrapping_mul(d2.wrapping_mul(d1).wrapping_sub(d3.wrapping_mul(d0)));
            let b = inv.wrapping_mul(d1.wrapping_mul(d3).wrapping_sub(d2.wrapping_mul(d2)));
            let c = z.wrapping_sub(prediction(a,b,0,x,y));
            if prediction(a,b,c,t,u) as u8 == s[pos+20] &&
                prediction(a,b,c,t,u) == word(s,pos+20) {
                let mut end = pos + 24;
                let (mut prev, mut last) = (u,word(s,pos+20));
                let limit = n.min(pos+65536);
                while end + 4 <= limit {
                    let val = prediction(a,b,c,prev,last);
                    if word(s,end) != val { break; }
                    (prev,last) = (last,val);
                    end += 4;
                }
                if end - pos >= min_span {
                    if found < cap {
                        output[found] = Hit{pos:pos as u32,len:(end-pos) as u32,a,b,c,x,y};
                    }
                    found += 1;
                    pos = end;
                    continue;
                }
            }
        }
        pos += step;
    }
    found
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rec2(dst: *mut u8, n: usize, a: u32,b: u32,c: u32,x: u32,y: u32) {
    let out = unsafe { from_raw_parts_mut(dst,n) };
    let (mut x, mut y) = (x,y);
    for chunk in out.chunks_mut(4) {
        chunk.copy_from_slice(&x.to_le_bytes()[..chunk.len()]);
        (x,y) = (y,prediction(a,b,c,x,y));
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn lfsr(dst: *mut u8, n: usize, degree: u32, taps: u64, seed: u64) {
    let out = unsafe { from_raw_parts_mut(dst,n) };
    let mut state = seed;
    let mask = (1u64 << degree) - 1;
    let mut initial = degree;
    for byte in out {
        let mut v = 0u8;
        for _ in 0..8 {
            let bit = if initial > 0 {
                initial -= 1;
                (seed >> initial) & 1
            } else {
                let bit = ((state & taps).count_ones() & 1) as u64;
                state = ((state << 1) | bit) & mask;
                bit
            };
            v = (v << 1) | bit as u8;
        }
        *byte = v;
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn xorshift(dst: *mut u8, n: usize, mut x: u32, little: u32) {
    let out = unsafe { from_raw_parts_mut(dst,n) };
    for chunk in out.chunks_mut(4) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        let bytes = if little == 0 { x.to_be_bytes() } else { x.to_le_bytes() };
        chunk.copy_from_slice(&bytes[..chunk.len()]);
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn rice(src: *const u64,n: usize,k: u32,dst: *mut u8,cap: usize) -> usize {
    if k > 64 { return usize::MAX; }
    let input = unsafe { from_raw_parts(src,n) };
    let out = unsafe { from_raw_parts_mut(dst,cap) };
    let (mut pos, mut bits, mut acc) = (0,0,0u128);
    let mut emit = |data: u128, len| {
        acc = (acc << len) | data;
        bits += len;
        while bits >= 8 {
            bits -= 8;
            *out.get_mut(pos)? = (acc >> bits) as u8;
            pos += 1;
        }
        acc &= (1 << bits)-1;
        Some(())
    };
    for &v in input {
        let mut q = (v as u128) >> k;
        if q > (cap as u128)*8 { return usize::MAX; }
        while q >= 64 {
            if emit(u64::MAX as u128,64).is_none() { return usize::MAX; }
            q -= 64;
        }
        if emit((1u128 << q)-1,q as u32).is_none() ||
            emit((v as u128) & ((1u128<<k)-1),k+1).is_none() {return usize::MAX;}
    }
    if bits > 0 {
        if pos >= cap { return usize::MAX; }
        out[pos] = (acc << (8-bits)) as u8;
        pos += 1;
    }
    pos
}

fn paeth(a:u8,b:u8,c:u8) -> u8 {
    let (a,b,c) = (a as i16,b as i16,c as i16);
    let p = a+b-c;
    let (pa,pb,pc) = ((p-a).abs(),(p-b).abs(),(p-c).abs());
    (if pa <= pb && pa <= pc { a } else if pb <= pc { b } else { c }) as u8
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn png_filter(src: *const u8, dst: *mut u8, fs: *const u8,
                                  w: usize, h: usize, px: usize, invert: usize) -> u32 {
    let s = unsafe { from_raw_parts(src,w*h) };
    let out = unsafe { from_raw_parts_mut(dst,w*h) };
    let filters = unsafe { from_raw_parts(fs,h) };
    for (row,&id) in filters.iter().enumerate() {
        if id > 4 {return 0;}
        for j in 0..w {
            let i = row*w+j;
            let hist = if invert != 0 { &out[..i] } else { &s[..i] };
            let a = if j >= px {hist[i-px]} else {0};
            let b = if row != 0 {hist[i-w]} else {0};
            let c = if j >= px && row != 0 {hist[i-w-px]} else {0};
            let p = match id {
                0 => 0,1 => a,2 => b,3 => ((a as u16 + b as u16)/2) as u8,_ => paeth(a,b,c),
            };
            out[i] = if invert != 0 {s[i].wrapping_add(p)} else {s[i].wrapping_sub(p)};
        }
    }
    1
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn spatial(src: *const u8, dst: *mut u8, w: usize, h: usize,
                               a: u32,b: u32,c: u32,d:u32, invert:usize) {
    let s = unsafe { from_raw_parts(src,w*h) };
    let out = unsafe { from_raw_parts_mut(dst,w*h) };
    for row in 0..h {
        for j in 0..w {
            let i = row*w+j;
            let hist = if invert != 0 { &out[..i] } else { &s[..i] };
            let x = if j != 0 {hist[i-1] as u32} else {0};
            let y = if row != 0 {hist[i-w] as u32} else {0};
            let z = if j != 0 && row != 0 {hist[i-w-1] as u32} else {0};
            let p = (a*x+b*y+c*z+d) as u8;
            out[i] = if invert != 0 {s[i].wrapping_add(p)} else {s[i].wrapping_sub(p)};
        }
    }
}
