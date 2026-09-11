import { useEffect, useRef, useState, type FormEvent } from "react";
import { X, LoaderCircle, ShieldCheck } from "lucide-react";
import type { OperatorImageAsset } from "../operatorDomain";
import type { LocalTaskSource } from "../agentDomain";
import { authorizeOperatorProjectSnapshot, listLocalTaskSources, loadOperatorAnnotations, OperatorApiError } from "../data/api";
import { canonicalizeJcs, sha256HexUtf8 } from "../data/jcs";
import { makeAcceptanceRequirements, type AcceptanceRow, type AnnotationRequirement } from "../snapshotAcceptance";
import "../styles/acceptance-compute.css";

interface Props {
  workspaceId: string; projectId: string; projectName: string; assets: OperatorImageAsset[];
  onClose: () => void; onCreated: (source: LocalTaskSource) => void;
}
export function SnapshotAcceptanceDialog({workspaceId,projectId,projectName,assets,onClose,onCreated}: Props) {
  const dialogRef=useRef<HTMLElement>(null);
  const [rows,setRows]=useState<AcceptanceRow[]>([]), [loading,setLoading]=useState(true), [busy,setBusy]=useState(false);
  const [error,setError]=useState(""), [uncertainSha,setUncertainSha]=useState("");
  const [purpose,setPurpose]=useState("用于本地视觉数据集交付前的标注复核与确定性检查。"), [vocabulary,setVocabulary]=useState("");
  const [reviewer,setReviewer]=useState(""), [note,setNote]=useState(""), [attested,setAttested]=useState(false), [page,setPage]=useState(0);
  useEffect(()=>{const before=document.activeElement;dialogRef.current?.focus();return()=>{if(before instanceof HTMLElement&&before.isConnected)before.focus();};},[]);
  useEffect(()=>{
    let active=true;
    void (async()=>{
      const result: AcceptanceRow[]=[];
      for(let i=0;i<assets.length;i+=6) {
        const chunk=await Promise.all(assets.slice(i,i+6).map(async asset=>({asset,state:await loadOperatorAnnotations(workspaceId,asset.asset_id),split:'train' as const,category:'',requirement:'UNKNOWN' as const})));
        if(!active) return;
        result.push(...chunk);
      }
      if(active){setRows(result);setVocabulary([...new Set(result.flatMap(row=>row.state.annotations.map(box=>box.label)))].join(", "));}
    })().catch(()=>{if(active)setError("当前标注版本读取失败，请关闭后重新打开复核。未创建快照。");}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[assets,workspaceId]);
  function update(index:number,patch:Partial<AcceptanceRow>){setRows(current=>current.map((row,i)=>i===index?{...row,...patch}:row));setAttested(false);}
  async function submit(event:FormEvent){
    event.preventDefault();if(busy||uncertainSha)return;setError("");
    let expectedSha="";
    try{
      const acceptance=makeAcceptanceRequirements({purpose,vocabulary,reviewer,note,attested,rows});
      expectedSha=await sha256HexUtf8(canonicalizeJcs(acceptance));setBusy(true);
      const source=await authorizeOperatorProjectSnapshot({workspaceId,projectId,displayName:`${projectName.slice(0,90)} · 已复核快照`,acceptanceRequirements:acceptance});
      if(source.data_profile.acceptance_requirements_sha256!==expectedSha) throw new Error("冻结回执与当前复核合同不一致。");
      onCreated(source);
    }catch(reason){
      const definitelyRejected=reason instanceof OperatorApiError && [400,409,422].includes(reason.status);
      if(expectedSha&&!definitelyRejected)setUncertainSha(expectedSha);
      setError(reason instanceof Error?reason.message:"无法确认冻结结果。请先查询已有快照，不要重复提交。");
    }finally{setBusy(false);}
  }
  async function reconcile(){setBusy(true);setError("");try{
    const sources=await listLocalTaskSources(workspaceId);
    const found=sources.find(source=>source.status==='active'&&source.data_profile.project_id===projectId&&source.data_profile.acceptance_requirements_sha256===uncertainSha);
    if(found)onCreated(found);else setError("尚未查到匹配的已授权快照。保持待对账，不自动重放冻结请求；可继续查询，或关闭后到来源管理核对。");
  }catch{setError("查询来源失败；冻结结果仍未知，请恢复连接后再次查询。");}finally{setBusy(false);}}
  const options=[...new Set(vocabulary.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean))];
  return <div className="acceptance-overlay"><section ref={dialogRef} tabIndex={-1} className="acceptance-dialog" role="dialog" aria-modal="true" aria-labelledby="acceptance-title" onKeyDown={event=>{
    event.stopPropagation();
    if(event.key==='Escape'){event.preventDefault();if(!busy)onClose();}
    if(event.key==='Tab'){
      const controls=[...event.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,textarea:enabled,select:enabled,a[href]')];
      const first=controls[0],last=controls.at(-1);
      if(!first){event.preventDefault();event.currentTarget.focus();}
      else if(event.shiftKey&&(document.activeElement===first||document.activeElement===event.currentTarget)){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  }}>
    <header><div><small>冻结前 · 人工确认输入要求</small><h2 id="acceptance-title">这批图像，按什么标准检查？</h2></div><button type="button" disabled={busy} onClick={onClose} aria-label="关闭验收要求"><X size={18}/></button></header>
    <p>本次包含项目全部 {assets.length} 张图片。标注语义由你复核；系统会再次核对图片摘要和标注版本。此确认不等于客户接受或生产放行。</p>
    {loading?<p role="status"><LoaderCircle size={16}/>正在读取全部标注版本…</p>:null}
    <form onSubmit={event=>void submit(event)}>
      <fieldset disabled={loading||busy||Boolean(uncertainSha)}>
        <div className="acceptance-fields"><label>本次用途说明<textarea value={purpose} minLength={8} maxLength={1000} required onChange={e=>{setPurpose(e.target.value);setAttested(false);}}/></label><label>数据类别与框标签词表<textarea value={vocabulary} placeholder="用逗号或换行分隔，必须包含已有框标签" required onChange={e=>{setVocabulary(e.target.value);setAttested(false);}}/></label></div>
        <p>每张图片的标注要求初始为“未明确”，请逐项选择。无标注不等于合格，已有标注也不等于已复核。</p>
        <div className="acceptance-table"><table><thead><tr><th>图片 / 当前版本</th><th>数据划分</th><th>样本类别</th><th>标注要求</th></tr></thead><tbody>{rows.slice(page*25,page*25+25).map((row,offset)=><tr key={row.asset.asset_id}><td>{assets.find(asset=>asset.asset_id===row.asset.asset_id)?.original_name}<small>Rev {row.state.revision} · {row.state.annotations.length} 个框</small></td><td><select aria-label={`划分 ${row.asset.asset_id}`} value={row.split} onChange={e=>update(page*25+offset,{split:e.target.value as AcceptanceRow['split']})}><option value="train">train</option><option value="val">val</option><option value="test">test</option></select></td><td><select aria-label={`类别 ${row.asset.asset_id}`} value={row.category} onChange={e=>update(page*25+offset,{category:e.target.value})}><option value="">请选择</option>{options.map(value=><option key={value}>{value}</option>)}</select></td><td><select aria-label={`标注要求 ${row.asset.asset_id}`} value={row.requirement} onChange={e=>update(page*25+offset,{requirement:e.target.value as AnnotationRequirement})}><option value="UNKNOWN">未明确 · 阻止冻结</option><option value="REQUIRED">必须有标注</option><option value="OPTIONAL">允许无标注</option><option value="NOT_APPLICABLE">标注不适用</option></select></td></tr>)}</tbody></table></div>
        <div className="acceptance-pagination"><button type="button" disabled={page===0} onClick={()=>setPage(page-1)}>上一页</button><span>{page+1} / {Math.max(1,Math.ceil(rows.length/25))}</span><button type="button" disabled={(page+1)*25>=rows.length} onClick={()=>setPage(page+1)}>下一页</button></div>
        <div className="acceptance-fields"><label>复核人姓名<input value={reviewer} required minLength={2} maxLength={120} onChange={e=>{setReviewer(e.target.value);setAttested(false);}}/></label><label>采用的标注规范与复核说明<textarea value={note} required minLength={8} maxLength={2000} onChange={e=>{setNote(e.target.value);setAttested(false);}}/></label></div>
        <label className="acceptance-attestation"><input type="checkbox" checked={attested} onChange={e=>setAttested(e.target.checked)}/>我已按上述规范复核本项目全部图片与标注，确认用途、划分和标注要求；本声明只绑定当前读取的版本。</label>
      </fieldset>
      {error?<p role="alert" className="acceptance-error">{error}</p>:null}
      <footer>{uncertainSha?<button type="button" disabled={busy} onClick={()=>void reconcile()}>仅查询已授权快照</button>:<button type="submit" disabled={loading||busy||rows.length!==assets.length||!attested}><ShieldCheck size={16}/>{busy?"正在核验并冻结…":"确认要求并冻结快照"}</button>}<small>不修改原图，不自动启动任务。结果未知时只查询，不自动重放写入。</small></footer>
    </form>
  </section></div>;
}
