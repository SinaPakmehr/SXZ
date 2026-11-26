use std::slice::{from_raw_parts,from_raw_parts_mut};

const J:u64=0x9e3779b97f4a7c15;
const A:u64=6364136223846793005;
fn split(mut x:u64)->u64 {x=(x^(x>>30)).wrapping_mul(0xbf58476d1ce4e5b9);x=(x^(x>>27)).wrapping_mul(0x94d049bb133111eb);x^(x>>31)}
fn mix2(mut x:u64)->u64 {x^=x>>33;x=x.wrapping_mul(0xff51afd7ed558ccd);x^=x>>33;x=x.wrapping_mul(0xc4ceb9fe1a85ec53);x^(x>>33)}
fn xstep(mut x:u32)->u32 {x^=x<<13;x^=x>>17;x^(x<<5)}
fn skip(mut x:u64,mut n:usize,mut a:u64,mut b:u64)->u64{
    while n>0 {if n&1!=0{x=x.wrapping_mul(a).wrapping_add(b);}
        b=b.wrapping_mul(a.wrapping_add(1));a=a.wrapping_mul(a);n>>=1;} x
}
fn gf(mut a:u8,mut b:u8)->u8 {let mut x=0;while b!=0{if b&1!=0{x^=a;} a=(a<<1)^(if a&128!=0{0x1b}else{0});b>>=1;} x}
fn bytes(f:u32,p:u32,seed:u32,start:usize,out:&mut [u8],table:&[u8]){
    let s=seed as u64;
    let n=out.len();
    if f==10 || f==11 { // map or first-order transition table driven by a counter
        let mut prev=0u8;
        for i in 0..start+n {
            let r=split((i as u64).wrapping_mul(J)^s);
            let b=if f==10 {table[(r&255) as usize]} else {table[prev as usize*16+(r&15) as usize]};
            if i>=start {out[i-start]=b;} prev=b;
        }
        return;
    }
    if f==7 || f==8 || f==9 {
        let mut a=(seed|1) as u64;
        for i in 0..start+n {
            let r=match f {
                7 => {let r=a as u8;a=gf(r, if p&1==0{3}else{5}) as u64 | (0x100 & a);r},
                8 => {let r=(a>>31) as u8;a=(a<<1)^(a|(a>>1));r},
                _ => {let r=a as u8;let taps=if p&1==0{0xb400}else{0x80200003};
                      for _ in 0..8{a=(a>>1)^if a&1!=0{taps}else{0};}r},
            };
            if i>=start {out[i-start]=r;}
        }
        return;
    }
    let w=if f==2 || f==3 || f==4 {4}else{8};
    let begin=start/w;
    let inc=if p&1==0 {1442695040888963407u64}else{1013904223};
    let ma=if p&1==0 {1664525}else{22695477};
    let mut a=match f {3=>skip(s,begin,A,inc),4=>skip(s,begin,ma,inc),
                        6=>split(s),_=>s};
    let mut b=split(s^J);
    if f==2 {for _ in 0..begin {a=xstep(a as u32) as u64;}}
    if f==6 {for _ in 0..begin{let r=b^a;a=a.rotate_left(24)^r^(r<<16);b=r.rotate_left(37);}}
    let mut wr=0;
    for i in begin..(start+n+w-1)/w {
        let z=match f {
            0=>split((i as u64).wrapping_mul(J).wrapping_add(s)),
            1=>mix2((i as u64).wrapping_mul(0xd1342543de82ef95).wrapping_add(s^0xa21c274e12f19d73)),
            2=>{let x=a;a=xstep(a as u32) as u64;x},
            3=>{let x=(((a>>18)^a)>>27) as u32;let r=(a>>59) as u32;
                a=a.wrapping_mul(A).wrapping_add(inc);x.rotate_right(r) as u64},
            4=>{let x=a as u32;a=a.wrapping_mul(ma).wrapping_add(inc);x as u64},
            5=>{let x=split(s.wrapping_add((i as u64).wrapping_mul(J)));
                let y=mix2((i as u64)^s.rotate_left(19)^0x87a5154f04ca56d1);
                match p {0=>x^y,1=>x.wrapping_add(y),2=>x.rotate_left(17),_=>if i%2==0{x}else{y}}},
            6=>{let x=a.wrapping_add(b);let r=a^b;a=a.rotate_left(24)^r^(r<<16);b=r.rotate_left(37);x},
            _=>0
        };
        let q=if i==begin {start%w}else{0};
        let k=(w-q).min(n-wr);
        out[wr..wr+k].copy_from_slice(&z.to_le_bytes()[q..q+k]);wr+=k;
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn generate(f:u32,p:u32,seed:u32,start:usize,d:*mut u8,n:usize,t:*const u8,tn:usize)->u32{
    if f>11 || start.checked_add(n).is_none_or(|x|x>262144) ||
        f==10 && tn!=256 || f==11 && tn!=4096 {return 0;}
    bytes(f,p,seed,start,unsafe{from_raw_parts_mut(d,n)},unsafe{from_raw_parts(t,tn)});
    1
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn matrix(f:u32,p:u32,ss:*const u32,rows:usize,stride:usize,d:*mut u8,t:*const u8,tn:usize)->u32{
    if rows>65536 || f>11 || stride>262144 || rows*stride>12_600_000 ||
       f==10 && tn!=256 || f==11 && tn!=4096 {return 0;}
    let out=unsafe{from_raw_parts_mut(d,rows*stride)};
    let table=unsafe{from_raw_parts(t,tn)};
    for (&s,line) in unsafe{from_raw_parts(ss,rows)}.iter().zip(out.chunks_mut(stride)){
        bytes(f,p,s,0,line,table);
    } 1
}

pub struct Index {d:Vec<u8>,strd:usize,k:usize,base:u32,factor:u32,ix:Vec<u64>,dir:Vec<u32>,shift:u32}
#[repr(C)]
#[derive(Clone,Copy)]
pub struct Hit {a:u32,row:u32,q:u32,n:u32}
#[repr(C)]
pub struct Stats {hits:u64,covered:u64,max:u64,sum:u64,multi:u64,dropped:u64,entries:u64}
fn key(d:&[u8],b:u32)->u32 {d.iter().fold(0,|q,&x|q*b+x as u32)}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn build(d:*const u8,n:usize,strd:usize,k:usize,b:u32)->*mut Index{
    if n>12_600_000 || !(2..=256).contains(&b) || !(2..=24).contains(&k) || strd<k || n%strd!=0 {return std::ptr::null_mut();}
    let Some(pow)=b.checked_pow(k as u32) else {return std::ptr::null_mut();};
    let data=unsafe{from_raw_parts(d,n)};
    if data.iter().any(|&x|x as u32>=b) {return std::ptr::null_mut();}
    let fact=pow/b;
    let mut ix=Vec::with_capacity(n);
    for (i,s) in data.chunks(strd).enumerate(){
        let mut x=key(&s[..k],b);
        for j in 0..=strd-k{
            ix.push(((x as u64)<<32)|(i*strd+j) as u64);
            if j+k<strd {x=(x-s[j] as u32*fact)*b+s[j+k] as u32;}
        }
    }
    ix.sort_unstable();
    let shift=(32-(pow-1).leading_zeros()).saturating_sub(16);
    let sz=((pow-1)>>shift) as usize+2;
    let mut dir=vec![0;sz];
    let mut p=0;
    for (i,e) in dir.iter_mut().enumerate(){
        while p<ix.len() && ix[p]>>32>>shift < i as u64 {p+=1;}
        *e=p as u32;
    }
    Box::into_raw(Box::new(Index{d:data.to_vec(),strd,k,base:b,factor:fact,ix,dir,shift}))
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn release(ix:*mut Index){if !ix.is_null(){drop(unsafe{Box::from_raw(ix)});}}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn query(ip:*const Index,d:*const u8,n:usize,out:*mut Hit,cap:usize,min:usize,s:*mut Stats)->usize{
    let ix=unsafe{&*ip};let d=unsafe{from_raw_parts(d,n)};let s=unsafe{&mut *s};
    let out=unsafe{from_raw_parts_mut(out,cap)};let k=ix.k;s.entries=ix.ix.len() as u64;
    if n<k || n>u32::MAX as usize || d.iter().any(|&v|v as u32>=ix.base){return 0;}
    let mut kk=key(&d[..k],ix.base);
    let(mut union,mut w)=(0,0);
    for a in 0..=n-k{
        let p=(kk>>ix.shift) as usize;
        let t=&ix.ix[ix.dir[p] as usize..ix.dir[p+1] as usize];
        let lo=t.partition_point(|&x|x>>32<kk as u64);
        if lo<t.len() && t[lo]>>32==kk as u64{
            let t=&t[lo..];let num=t.partition_point(|&x|x>>32==kk as u64);
            let mut best=0;
            for i in 0..num.min(6){
                let pos=t[if num<=6{i}else{i*(num-1)/5}] as u32 as usize;
                if d[a..a+k]!=ix.d[pos..pos+k] {continue;}
                let mut len=k;let q=pos%ix.strd;
                let lim=512.min(n-a).min(ix.strd-q);
                while len+16<=lim && d[a+len..a+len+16]==ix.d[pos+len..pos+len+16]{len+=16;}
                while len<lim && d[a+len]==ix.d[pos+len]{len+=1;}
                best=best.max(len);
                if len>=min{
                    if w<cap {out[w]=Hit{a:a as u32,row:(pos/ix.strd) as u32,q:q as u32,n:len as u32};w+=1;}
                    else{s.dropped+=1;}
                }
            }
            if best>0 {
                s.hits+=1;s.max=s.max.max(best as u64);s.sum+=best as u64;s.multi+=u64::from(num>1);
                if a+best>union{s.covered+=(a+best-a.max(union)) as u64;union=a+best;}
            }
        }
        if a+k<n{kk=(kk-d[a] as u32*ix.factor)*ix.base+d[a+k] as u32;}
    }
    w
}
