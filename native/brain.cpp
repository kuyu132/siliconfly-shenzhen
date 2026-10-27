// CPU port of SiliconFly LIF.metal. All neurons/edges, 1 ms biological steps.
// No Metal, GPU, Python numerical package or network dependency.
#include "layout.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <omp.h>

template<class T> std::vector<T> read(const std::string& file, size_t offset, size_t n) {
    std::ifstream f(file, std::ios::binary); f.seekg(offset);
    std::vector<T> a(n); f.read(reinterpret_cast<char*>(a.data()), n*sizeof(T));
    if (!f) throw std::runtime_error("Invalid data: "+file);
    return a;
}
uint32_t pcg(uint32_t x) {
    uint32_t s=x*747796405u+2891336453u;
    uint32_t w=((s>>((s>>28u)+4u))^s)*277803737u;
    return (w>>22u)^w;
}
float unit(uint32_t x) { return float(x>>8)*5.9604645e-8f; }
constexpr uint32_t SEED=0x5EED1F1F;
float draw(uint32_t salt, uint32_t i) {return unit(pcg(pcg(SEED+salt)+i));}

struct Brain {
    std::vector<uint32_t> row, col;
    std::vector<int32_t> weights;
    // Int64 sums avoid overflow at unusually large synchronous activity.
    std::vector<int64_t> exc, inh;
    std::vector<uint8_t> role, side, kind, group, refr;
    std::vector<float> v, base, phase, pos;
    std::array<unsigned,9> sizes{};
    std::array<float,9> rates{};
    std::vector<uint32_t> spikes;
    std::array<std::vector<uint32_t>,4> threadSpikes;
    std::array<int,32> samples{};
    uint64_t ms=0, total=0, gfEvents=0, burstNext=12000, burstUntil=0;
    unsigned burstCounter=0;
    float fx=1048576;
    explicit Brain(std::string dir) {
        auto nf=dir+"/neurons.bin", sf=dir+"/synapses.bin";
        row=read<uint32_t>(nf,OFF_rowStart,N+1); col=read<uint32_t>(sf,OFF_colIdx,E);
        auto raw=read<int16_t>(sf,OFF_weight,E);
        role=read<uint8_t>(nf,OFF_role,N); side=read<uint8_t>(nf,OFF_side,N);
        auto nt=read<uint8_t>(nf,OFF_nt,N), cl=read<uint8_t>(nf,OFF_superClass,N);
        pos=read<float>(nf,OFF_pos,N*3);
        if(row[0]!=0 || row[N]!=E) throw std::runtime_error("CSR row extent");
        for(unsigned i=0;i<N;i++) if(row[i]>row[i+1]) throw std::runtime_error("CSR order");
        for(auto c:col) if(c>=N) throw std::runtime_error("CSR column bounds");
        kind.resize(N); group.resize(N); refr.resize(N); base.resize(N); phase.resize(N);
        v.resize(N); exc.resize(N); inh.resize(N*5); weights.resize(E); spikes.reserve(N);
        auto gain=[&](unsigned i,unsigned k) {
            if(role[col[k]]!=3) return 1.f;
            return role[i]==1 || role[i]==2 ? .5f : role[i]==11 ? 1.5f : .12f;
        };
        float maxAbs=0;
        for(unsigned i=0;i<N;i++) {
            float scale=.0032f*(nt[i]>=4 ? .5f:1.f);
            for(unsigned k=row[i];k<row[i+1];k++) maxAbs=std::max(maxAbs,std::abs(float(raw[k])*scale*gain(i,k)));
        }
        while(fx>65536 && double(maxAbs)*fx*4096>INT32_MAX) fx/=2;
        for(unsigned i=0;i<N;i++) {
            float scale=.0032f*(nt[i]>=4 ? .5f:1.f)*fx;
            for(unsigned k=row[i];k<row[i+1];k++) weights[k]=int32_t(std::round(float(raw[k])*scale*gain(i,k)));
            float low=.019f, high=.043f;
            if(cl[i]==0 || cl[i]==3) {low=.021f;high=.043f;}
            if(cl[i]==1) {low=.023f;high=.047f;}
            if(cl[i]==2) {low=0;high=.004f;}
            if(cl[i]==9) {low=0;high=.006f;}
            if(role[i]==1 || role[i]==2) {low=.008f;high=.028f;kind[i]=side[i]==1?1:2;group[i]=1;}
            else if(role[i]==3) {low=high=.002f;group[i]=2;}
            else if(role[i]==4 || role[i]==5) {low=high=.022f;group[i]=side[i]==1?3:4;}
            else if(role[i]==6) {low=high=.032f;group[i]=6;}
            else if(role[i]==7) {low=high=.022f;group[i]=7;}
            else if(role[i]==8) {low=high=.022f;group[i]=5;}
            else if(role[i]==9) {low=high=.022f;group[i]=8;}
            else if(role[i]==10) {kind[i]=3;phase[i]=6.2831853f*draw(0x2F1B3C4D,i);}
            else if(role[i]==11) kind[i]=4;
            base[i]=low+(high-low)*draw(0x51ED2701,i);
            sizes[group[i]]++;
        }
        sizes[0]=N;
        std::cerr<<"K3 CPU brain: "<<N<<" neurons, "<<E<<" edges, fixed scale "<<fx<<"\n";
    }
    bool step(float activity,float left,float right,float gait,float gaitPh,float air,bool blockGF) {
        ++ms;
        if(ms>=burstNext) {
            burstUntil=ms+400;
            burstNext=ms+15000+unsigned(draw(0x7A3B9F11,++burstCounter)*25001);
        }
        unsigned cur=((ms-1)%5)*N, target=((ms-1+4)%5)*N;
        uint32_t noiseSeed=pcg(SEED+uint32_t(ms)*2654435761u);
        float noise=.005f*activity*(ms<burstUntil?6.f:1.f);
        std::array<unsigned,9> counts{};
        spikes.clear(); samples.fill(-1);
        for(auto& list:threadSpikes) list.clear();
        #pragma omp parallel for num_threads(4) schedule(static)
        for(unsigned i=0;i<N;i++) {
            float vi=std::max(-2.f,v[i]+float(exc[i])/fx); exc[i]=0;
            unsigned r=refr[i]; uint32_t h=pcg(noiseSeed+i);
            if(r) {refr[i]--;vi*=.9512f;}
            else {vi=std::fma(vi,.9512f,base[i]*activity);if(unit(h)<noise) vi+=.25f;}
            switch(kind[i]) {
                case 1:vi+=left*.32f;break;
                case 2:vi+=right*.32f;break;
                case 3:vi+=gait*.09f*(.5f+.5f*std::sin(gaitPh*6.2831853f+phase[i]));break;
                case 4:vi+=air*.05f;break;
            }
            vi=std::max(-2.f,vi+float(inh[cur+i])/fx); inh[cur+i]=0;
            if(blockGF && role[i]==3) vi=0; // actual neuron clamp, not output hiding
            if(r<=1 && vi>=1) {
                vi=0; refr[i]=2; threadSpikes[omp_get_thread_num()].push_back(i);
            }
            v[i]=vi;
        }
        for(const auto& list:threadSpikes) for(auto i:list) {
            spikes.push_back(i);counts[group[i]]++;
            samples[(pcg(noiseSeed+i)>>3)&31]=i;
        }
        for(auto i:spikes) for(unsigned k=row[i];k<row[i+1];k++) {
            if(weights[k]>=0) exc[col[k]]+=weights[k]; else inh[target+col[k]]+=weights[k];
        }
        total+=spikes.size(); counts[0]=spikes.size();
        for(unsigned g=0;g<9;g++) rates[g]+=(float(counts[g])*1000/std::max(1u,sizes[g])-rates[g])/120;
        if(counts[2]) ++gfEvents;
        return counts[2]>0;
    }
    void run(unsigned steps,float activity,float left,float right,float gait,float gaitPh,float air,bool blockGF) {
        auto start=std::chrono::steady_clock::now(); bool gf=false;
        for(unsigned i=0;i<steps;i++) gf=step(activity,left,right,gait,gaitPh,air,blockGF)||gf;
        double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count()/steps;
        std::cout<<"{\"sim_ms\":"<<ms<<",\"step_us\":"<<us<<",\"neurons\":"<<N<<",\"edges\":"<<E
          <<",\"population_hz\":"<<rates[0]<<",\"loom_hz\":"<<rates[1]<<",\"forward_hz\":"<<rates[6]
          <<",\"groom_hz\":"<<rates[7]<<",\"left_hz\":"<<rates[3]<<",\"right_hz\":"<<rates[4]
          <<",\"backward_hz\":"<<rates[5]<<",\"gf_events\":"<<gfEvents<<",\"gf_active\":"<<(gf?1:0)
          <<",\"total_spikes\":"<<total<<",\"spikes\":[";
        bool first=true;
        for(int i:samples) if(i>=0) {
            if(!first) std::cout<<",";
            first=false;
            std::cout<<"["<<i<<","<<pos[i*3]<<","<<pos[i*3+1]<<","<<pos[i*3+2]<<"]";
        }
        std::cout<<"]}"<<std::endl;
    }
};
int main(int argc,char**argv) {
    try {
        Brain brain(argc>1?argv[1]:"data");
        unsigned steps;float activity,left,right,gait,phase,air;int block;
        while(std::cin>>steps>>activity>>left>>right>>gait>>phase>>air>>block) {
            if(steps<1 || steps>1000 || !std::isfinite(activity) || activity<0 || activity>2 ||
               !std::isfinite(left+right+gait+phase+air) || left<0 || left>1 || right<0 || right>1 || gait<0 || gait>2)
                throw std::runtime_error("Input bounds");
            brain.run(steps,activity,left,right,gait,phase,air,block!=0);
        }
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}
}
