import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MatchesAndClaims } from '../src/IndividualPortal';
import { ClaimReview } from '../src/StaffPortal';
import { useReportMatches } from '../src/useReportMatches';
import { DEMO_CHANGE, DemoApi, readDemoState, resetDemo } from './claims-demo-api';
import '../src/styles.css';

const api = new DemoApi();

function DemoSession() {
  const [role, setRole] = useState<'individual' | 'staff'>('individual');
  const [snapshot, setSnapshot] = useState(readDemoState);
  const { reports, matches, error, refresh } = useReportMatches(api);

  useEffect(() => {
    const update = () => setSnapshot(readDemoState());
    window.addEventListener(DEMO_CHANGE, update);
    return () => window.removeEventListener(DEMO_CHANGE, update);
  }, []);

  return <>
    <div className="btn-row" style={{ marginBottom: '1rem' }}>
      <button type="button" aria-pressed={role === 'individual'} className={role === 'individual' ? '' : 'secondary'}
        onClick={() => { setRole('individual'); void refresh(true); }}>个人视角</button>
      <button type="button" aria-pressed={role === 'staff'} className={role === 'staff' ? '' : 'secondary'}
        onClick={() => setRole('staff')}>工作人员视角</button>
    </div>
    {role === 'individual'
      ? <MatchesAndClaims api={api} reports={reports} matches={matches} error={error} refresh={refresh} />
      : <ClaimReview api={api} />}
    <details className="card" style={{ marginTop: '1rem' }}>
      <summary>查看本地模拟认领记录</summary>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(snapshot.claims, null, 2)}</pre>
    </details>
  </>;
}

function ClaimsDemo() {
  const [session, setSession] = useState(0);
  return <main className="page">
    <section className="card" style={{ marginBottom: '1rem' }}>
      <h1>LostLink 本地认领演示</h1>
      <p>使用真实页面组件和浏览器模拟数据，记录会保存在当前浏览器。文字证据可直接填写。</p>
      <p>先认领钱包，再切换工作人员要求补证、批准或拒绝。第二条匹配会在约 8 秒内自动出现。</p>
      <p className="notice info">本页验证界面流程。AWS 事务、权限、邮件和 AI 匹配需要单独联调。</p>
      <button type="button" className="secondary sm" onClick={() => { resetDemo(); setSession((value) => value + 1); }}>重置演示数据</button>
    </section>
    <DemoSession key={session} />
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><ClaimsDemo /></React.StrictMode>);
