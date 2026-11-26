use std::collections::HashMap;
use std::slice::{from_raw_parts, from_raw_parts_mut};

const LIM: usize = 4096;
const SAMPLE: usize = 8;

pub struct Index {
    text: Vec<u8>,
    bounds: Vec<u32>,
    entries: Vec<u64>,
    dir: Vec<u32>,
    shift: u32,
    base: u32,
    k: usize,
    radix: u32,
}

#[repr(C)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Hit { pub target: u32, pub start: u32, pub len: u32, pub gid: u32 }

#[repr(C)]
pub struct Stats {
    pub count: u64, pub sum: u64, pub covered: u64, pub best: u64,
    pub repeated_key: u64, pub candidates: u64, pub dropped: u64, pub nentries: u64,
    pub pos: [u64; 10], pub source: [u64; 64], pub hist: [u64; 16],
}

fn key(s: &[u8], base: u32) -> u32 {
    s.iter().fold(0,|d,&v|d*base+v as u32)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn make(data:*const u8,n:usize,bd:*const u32,nb:usize,
                               base:u32,k:usize) -> *mut Index {
    if n>10_000_000 || !(2..=257).contains(&base) || !(2..=24).contains(&k) || !(2..=65).contains(&nb) {
        return std::ptr::null_mut();
    }
    let Some(pow)=base.checked_pow(k as u32) else {return std::ptr::null_mut();};
    let r=pow/base;
    let d=unsafe{from_raw_parts(data,n)};
    let b=unsafe{from_raw_parts(bd,nb)};
    if b[0]!=0 || b[nb-1] as usize!=n || b.windows(2).any(|i|i[0]>=i[1]) ||
       d.iter().any(|&v|v as u32>=base) {return std::ptr::null_mut();}
    let mut en=Vec::with_capacity(n);
    for p in b.windows(2) {
        let (a,z)=(p[0] as usize,p[1] as usize);
        if z-a<k {continue;}
        let mut u=key(&d[a..a+k],base);
        for i in a..=z-k {
            en.push(((u as u64)<<32) | (i as u64));
            if i+k<z {u=(u-d[i] as u32*r)*base+d[i+k] as u32;}
        }
    }
    en.sort_unstable();
    let shift=(32-(pow-1).leading_zeros()).saturating_sub(15);
    let size=((pow-1)>>shift) as usize+2;
    let mut dir=vec![0;size];
    let mut addr=0;
    for (i,v) in dir.iter_mut().enumerate() {
        while addr<en.len() && (en[addr]>>32>>shift)<i as u64 {addr+=1;}
        *v=addr as u32;
    }
    Box::into_raw(Box::new(Index{text:d.to_vec(),bounds:b.to_vec(),entries:en,dir,shift,base,k,radix:r}))
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn free(ptr:*mut Index) {
    if !ptr.is_null() { drop(unsafe{Box::from_raw(ptr)}); }
}

fn run(s:&[u8],i:usize,end:usize) -> usize {
    let v=s[i]; let mut j=i+1;
    while j+16<=end && s[j..j+16]==[v;16] {j+=16;}
    while j<end && s[j]==v {j+=1;}
    j
}

fn lcp(a:&[u8],b:&[u8],mut p:usize,lim:usize) -> usize {
    while p+16<=lim && a[p..p+16]==b[p..p+16] {p+=16;}
    while p<lim && a[p]==b[p] {p+=1;}
    p
}

fn vlen(mut i:u32)->i64 {
    let mut n=1;
    while i>=128 {n+=1;i>>=7;}
    n
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn search(ptr:*const Index,p:*const u8,n:usize,buf:*mut Hit,cap:usize,
     min_len:usize, score_factor:u32, summary:*mut Stats) -> usize {
    let ix=unsafe{&*ptr};
    let s=unsafe{from_raw_parts(p,n)};
    let result=unsafe{from_raw_parts_mut(buf,cap)};
    let st=unsafe{&mut *summary};
    let k=ix.k;
    st.nentries=ix.entries.len() as u64;
    if n<k || n>u32::MAX as usize || s.iter().any(|&v|v as u32>=ix.base) {return 0;}
    let mut u=key(&s[..k],ix.base);
    let mut wrote=0;
    let mut union_end=0;
    let mut run_end=0;
    let mut rcache:HashMap<usize,usize>=HashMap::new();
    for i in 0..=n-k {
        let buck=(u>>ix.shift) as usize;
        let e=&ix.entries[ix.dir[buck] as usize..ix.dir[buck+1] as usize];
        let left=e.partition_point(|&x|(x>>32)<u as u64);
        if left<e.len() && e[left]>>32==u as u64 {
            let e=&e[left..];
            let nr=e.partition_point(|&x|(x>>32)==u as u64);
            if nr>1 {st.repeated_key+=1;}
            let mut longest=Hit{target:i as u32,start:0,len:0,gid:0};
            let mut cheap=longest;
            let mut best_score=i64::MIN;
            let mono=s[i]==s[i+k-1] && s[i..i+k].iter().all(|&x|x==s[i]);
            if mono && i>=run_end {run_end=run(s,i,n);}
            let ne=nr.min(SAMPLE);
            for j in 0..ne {
                let off=e[if nr<=SAMPLE {j} else {j*(nr-1)/(SAMPLE-1)}] as u32;
                let gid=ix.bounds.partition_point(|&x|x<=off)-1;
                let max= (ix.bounds[gid+1]-off) as usize;
                let o=off as usize;
                if s[i..i+k]!=ix.text[o..o+k] {continue;}
                let lim=LIM.min(n-i).min(max);
                let mut from=k;
                if mono {
                    let r=if let Some(&x)=rcache.get(&o) {x} else {
                        let r=run(&ix.text,o,o+max);
                        if rcache.len()<16384 {rcache.insert(o,r);}
                        r
                    };
                    from=lim.min(run_end-i).min(r-o);
                }
                let m=lcp(&s[i..],&ix.text[o..],from,lim);
                let h=Hit{target:i as u32,start:off-ix.bounds[gid],len:m as u32,gid:gid as u32};
                let sc=m as i64 - score_factor as i64*vlen(h.start);
                if sc>best_score || sc==best_score && h.start<cheap.start {cheap=h;best_score=sc;}
                if m as u32>longest.len || m as u32==longest.len && h.start<longest.start {longest=h;}
            }
            if longest.len>0 {
                let m=longest.len as usize;
                st.count+=1; st.sum+=m as u64; st.best=st.best.max(m as u64);
                st.pos[(10*i/n).min(9)]+=1; st.source[longest.gid as usize]+=1;
                st.hist[(usize::BITS-m.leading_zeros()-1) as usize]+=1;
                if i+m>union_end {st.covered+=(i+m-union_end.max(i)) as u64; union_end=i+m;}
                for (j,h) in [longest,cheap].into_iter().enumerate() {
                    if (h.len as usize)<min_len || j==1 && h==longest {continue;}
                    st.candidates+=1;
                    if wrote<cap {result[wrote]=h;wrote+=1;} else {st.dropped+=1;}
                }
            }
        }
        if i+k<n {u=(u-s[i] as u32*ix.radix)*ix.base+s[i+k] as u32;}
    }
    wrote
}
