<template>
  <main id="guide-top" class="usage-guide">
    <a class="guide-skip" href="#guide-content">跳到指南正文</a>
    <div class="guide-layout">
      <aside class="guide-sidebar" aria-label="指南目录">
        <a class="guide-home" href="#guide-top"><span class="guide-mark" aria-hidden="true">讲</span><span>AI 自讲<span class="guide-home-caption">使用指南</span></span></a>
        <nav aria-label="桌面章节导航">
          <p class="guide-nav-label">01 / 学生教师通用</p>
          <a href="#account">注册与登录</a>
          <a href="#questions">查找题目与开始自讲</a>
          <a href="#workspace">认识自讲页面</a>
          <a href="#input">输入并提交自讲</a>
          <a href="#grading">查看首次自讲评分</a>
          <a href="#feedback">根据 AI 反馈继续自讲</a>
          <a href="#doubts">使用“我有疑问”</a>
          <a href="#mastery">完整解析与掌握度核验</a>
          <a href="#speech">收听回复与设置音色</a>
          <a href="#history">回看记录与重新自讲</a>
          <p class="guide-nav-label">02 / 教师专用</p>
          <a href="#question-details">题目详情与评价材料</a>
          <a href="#question-editor">录入与编辑题目</a>
          <a href="#archive">归档与恢复题目</a>
          <a href="#logs">查看运行日志</a>
        </nav>
        <p class="guide-sidebar-note">按实际页面操作。子问题、解析和核验会随学习进度出现。</p>
      </aside>

      <div id="guide-content" class="guide-reader">
        <header class="guide-intro">
          <p class="guide-eyebrow">AI 自讲 · 教师测试用</p>
          <h1>AI 自讲使用指南</h1>
          <p class="guide-lead">先体验一道题的自讲过程，再了解题目管理与运行日志。学生和教师共用的操作放在前半部分，教师专用功能放在后半部分。</p>
          <div class="guide-shortcuts" aria-label="快速阅读入口">
            <a class="guide-primary-link" href="#input">开始体验自讲 <span aria-hidden="true">↗</span></a>
            <a href="#question-details">查看教师功能 <span aria-hidden="true">↓</span></a>
          </div>
          <details class="guide-mobile-directory">
            <summary>阅读目录 <span>共 14 节</span></summary>
            <nav aria-label="移动端章节导航">
              <p class="guide-nav-label">学生教师通用</p>
              <a href="#account">1.1 注册与登录</a>
              <a href="#questions">1.2 查找题目与开始自讲</a>
              <a href="#workspace">1.3 认识自讲页面</a>
              <a href="#input">1.4 输入并提交自讲</a>
              <a href="#grading">1.5 查看首次自讲评分</a>
              <a href="#feedback">1.6 根据 AI 反馈继续自讲</a>
              <a href="#doubts">1.7 使用“我有疑问”</a>
              <a href="#mastery">1.8 完整解析与掌握度核验</a>
              <a href="#speech">1.9 收听回复与设置音色</a>
              <a href="#history">1.10 回看记录与重新自讲</a>
              <p class="guide-nav-label">教师专用</p>
              <a href="#question-details">2.1 题目详情与评价材料</a>
              <a href="#question-editor">2.2 录入与编辑题目</a>
              <a href="#archive">2.3 归档与恢复题目</a>
              <a href="#logs">2.4 查看运行日志</a>
            </nav>
          </details>
        </header>

        <section class="guide-group" aria-labelledby="common-title">
          <header class="guide-group-heading">
            <span class="guide-group-number" aria-hidden="true">01</span>
            <div><p class="guide-eyebrow">学生教师通用</p><h2 id="common-title">体验自讲的完整过程</h2><p>教师可以直接用自己的账号，体验选题、讲解、获得反馈和核验的过程。</p></div>
          </header>

          <section id="account" class="guide-section" aria-labelledby="account-title">
            <h3 id="account-title"><span>1.1</span>注册与登录</h3>
            <p>打开 AI 自讲后，在登录页输入用户名和密码，点击<span class="guide-control">登录</span>。没有账号时，点击<span class="guide-control">注册账号</span>。</p>
            <ol>
              <li>在注册页填写用户名、密码和姓名，密码至少 6 位。</li>
              <li>点击<span class="guide-control">注册</span>，成功后返回登录页，用刚注册的账号登录。</li>
              <li>登录后进入题目列表。离开时，可从顶部<span class="guide-control">菜单</span>选择<span class="guide-control">退出登录</span>。</li>
            </ol>
            <p class="guide-note">当前测试版注册的账号具有教师权限，可用同一账号体验自讲和教师专用功能。</p>
            <figure class="guide-shot" data-screenshot="01">
              <!-- 补图时将 guide-shot-space 替换为带有 alt 的 img，保留图号和说明。 -->
              <div class="guide-shot-space"><span class="guide-shot-number">01</span><div><strong>登录页与注册页</strong><span>截图待补充</span></div></div>
              <figcaption>图 01 · 登录、注册及页面切换入口。</figcaption>
            </figure>
          </section>

          <section id="questions" class="guide-section" aria-labelledby="questions-title">
            <h3 id="questions-title"><span>1.2</span>查找题目与开始自讲</h3>
            <p>在题目列表中选择要体验的题目。可以按学段、学科筛选，也可以输入题干关键词或题目 ID，再点击<span class="guide-control">搜索</span>。</p>
            <ul>
              <li>通过列表底部分页切换题目。</li>
              <li>查看“自讲进度”：<span class="guide-control">未尝试</span>表示尚未开始，<span class="guide-control">尝试过</span>表示已有尝试，<span class="guide-control">已完成</span>表示已完成过学习。</li>
              <li>“评价方式”列显示这道题使用的评价材料类型，具体含义见<a href="#question-details">题目详情与评价材料</a>。</li>
            </ul>
            <p>找到题目后，点击<span class="guide-control">开始自讲</span>。同一账号在这道题上已有进行中的会话时，会继续该会话。</p>
            <figure class="guide-shot" data-screenshot="02">
              <div class="guide-shot-space"><span class="guide-shot-number">02</span><div><strong>题目列表</strong><span>截图待补充</span></div></div>
              <figcaption>图 02 · 筛选、搜索、自讲进度和“开始自讲”入口。</figcaption>
            </figure>
          </section>

          <section id="workspace" class="guide-section" aria-labelledby="workspace-title">
            <h3 id="workspace-title"><span>1.3</span>认识自讲页面</h3>
            <p>进入自讲后，主要使用以下几个区域：</p>
            <dl class="guide-definitions">
              <div><dt>题目区</dt><dd>阅读本次自讲的题干。</dd></div>
              <div><dt>学习反馈区</dt><dd>查看 AI 的评价、纠错、提示、追问或核验结果。</dd></div>
              <div><dt>输入区</dt><dd>提交自讲，或切换到“回答子问题”“掌握度核验”“我有疑问”。</dd></div>
              <div><dt>历史记录区</dt><dd>回看本轮提交和已生成的学习反馈。</dd></div>
            </dl>
            <p>“回答子问题”和“掌握度核验”会在对应学习阶段出现。顶部<span class="guide-control">菜单</span>提供“重新自讲”“自讲历史”等入口；齿轮形的<span class="guide-control">设置</span>用于调整老师语音。</p>
            <figure class="guide-shot" data-screenshot="03">
              <div class="guide-shot-space"><span class="guide-shot-number">03</span><div><strong>自讲页面全貌</strong><span>截图待补充</span></div></div>
              <figcaption>图 03 · 题目、学习反馈、输入和历史记录区域。</figcaption>
            </figure>
          </section>

          <section id="input" class="guide-section" aria-labelledby="input-title">
            <h3 id="input-title"><span>1.4</span>输入并提交自讲</h3>
            <p>在<span class="guide-control">自讲</span>中表达自己的解题过程。除了写出答案，也应讲清关键步骤和这样做的理由。</p>
            <div class="guide-input-methods">
              <div><h4>文字输入</h4><p>在输入框中填写思路、步骤和依据，完成后点击<span class="guide-control">提交</span>。</p></div>
              <div><h4>语音输入</h4><p>点击<span class="guide-control">语音输入</span>，允许浏览器使用麦克风，讲述解题过程。结束语音输入后，点击<span class="guide-control">提交</span>。</p></div>
              <div><h4>插入公式</h4><p>点击<span class="guide-control">插入公式</span>，在公式编辑界面填写表达式，将公式与文字一起提交。</p></div>
            </div>
            <p>提交后系统会生成自讲评价和学习反馈。语音输入和公式输入也可用于回答子问题、掌握度核验及提问。</p>
            <figure class="guide-shot" data-screenshot="04">
              <div class="guide-shot-space"><span class="guide-shot-number">04</span><div><strong>自讲输入区与操作按钮</strong><span>截图待补充</span></div></div>
              <figcaption>图 04 · “提交”“语音输入”和“插入公式”。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="05">
              <div class="guide-shot-space"><span class="guide-shot-number">05</span><div><strong>公式输入界面</strong><span>截图待补充</span></div></div>
              <figcaption>图 05 · 公式填写与插入后的显示效果。</figcaption>
            </figure>
          </section>

          <section id="grading" class="guide-section" aria-labelledby="grading-title">
            <h3 id="grading-title"><span>1.5</span>查看首次自讲评分</h3>
            <p>首次提交后，查看<span class="guide-control">自讲评价</span>。总分满分为 100 分，包含两个各占 50% 的维度：</p>
            <dl class="guide-definitions">
              <div><dt>正确性</dt><dd>已表达的内容是否成立，得分为 0～4 档。</dd></div>
              <div><dt>完整性</dt><dd>本题必要内容是否覆盖，得分为 0～4 档。</dd></div>
            </dl>
            <p class="guide-formula">总分 =（正确性 + 完整性）÷ 8 × 100</p>
            <p>先看各维度的评价依据，再按需展开<span class="guide-control">评分标准与总分计算</span>和<span class="guide-control">查看本次提交原文</span>，了解评价对应的内容。</p>
            <p>点击<span class="guide-control">返回自讲</span>继续学习，也可通过<span class="guide-control">查看评价</span>再次打开结果。首次评分保留首次提交的原文；之后补充或修改自讲内容，通过后续学习反馈继续跟进。</p>
            <figure class="guide-shot" data-screenshot="06">
              <div class="guide-shot-space"><span class="guide-shot-number">06</span><div><strong>首次自讲评价</strong><span>截图待补充</span></div></div>
              <figcaption>图 06 · 总分、正确性、完整性及评价依据。</figcaption>
            </figure>
          </section>

          <section id="feedback" class="guide-section" aria-labelledby="feedback-title">
            <h3 id="feedback-title"><span>1.6</span>根据 AI 反馈继续自讲</h3>
            <p>阅读学习反馈，了解需要纠正或补充的地方。AI 可能指出错误、给出提示，也可能针对某个步骤追问。</p>
            <ol>
              <li>根据反馈回到<span class="guide-control">自讲</span>，补充步骤、结论或理由，再次提交。</li>
              <li>如果出现<span class="guide-control">回答子问题</span>，先阅读问题，再在对应输入框中回答。</li>
              <li>子问题逐题提交。完成回答后，阅读新的引导，并按页面提示继续学习。</li>
            </ol>
            <p>回答子问题时，可以直接输入文字，也可以使用<span class="guide-control">语音输入</span>或<span class="guide-control">插入公式</span>。</p>
            <figure class="guide-shot" data-screenshot="07">
              <div class="guide-shot-space"><span class="guide-shot-number">07</span><div><strong>AI 学习反馈</strong><span>截图待补充</span></div></div>
              <figcaption>图 07 · 纠错、提示或追问的实际示例。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="08">
              <div class="guide-shot-space"><span class="guide-shot-number">08</span><div><strong>回答子问题</strong><span>截图待补充</span></div></div>
              <figcaption>图 08 · 子问题、回答输入框及逐题提交入口。</figcaption>
            </figure>
          </section>

          <section id="doubts" class="guide-section" aria-labelledby="doubts-title">
            <h3 id="doubts-title"><span>1.7</span>使用“我有疑问”</h3>
            <p>对题目条件、某一步的推理或 AI 的反馈不理解时，切换到<span class="guide-control">我有疑问</span>，说清具体想问什么。</p>
            <ol>
              <li>输入疑问，可以使用文字、语音或公式。</li>
              <li>点击<span class="guide-control">提交</span>，查看 AI 的答疑内容。</li>
              <li>在答疑记录中回看自己问过的问题和对应回复。</li>
            </ol>
            <p class="guide-note">需要解释时使用“我有疑问”；补充自己的解题过程时，回到“自讲”提交。</p>
            <figure class="guide-shot" data-screenshot="09">
              <div class="guide-shot-space"><span class="guide-shot-number">09</span><div><strong>提问与答疑记录</strong><span>截图待补充</span></div></div>
              <figcaption>图 09 · 疑问输入区，以及一组问题和回复。</figcaption>
            </figure>
          </section>

          <section id="mastery" class="guide-section" aria-labelledby="mastery-title">
            <h3 id="mastery-title"><span>1.8</span>完整解析与掌握度核验</h3>
            <p>系统展示完整解析时，先阅读解题过程。如果已经理解，点击<span class="guide-control">我会了，进入掌握度核验</span>；仍有困难时，点击<span class="guide-control">仍然不会</span>。</p>
            <h4>回答核验问题</h4>
            <ol>
              <li>阅读老师回复中的核验问题，在对应输入框填写回答。</li>
              <li>可以使用文字、语音或公式，全部问题答完后统一点击<span class="guide-control">提交</span>。</li>
              <li>查看每个问题的核验结果及理由。</li>
            </ol>
            <p>阅读解析表示已经看过解法；点击“我会了”表达自己的理解情况；通过核验则需要用实际回答说明掌握情况。</p>
            <dl class="guide-definitions">
              <div><dt>学习成功</dt><dd>页面提示本轮完成，或核验通过、本题学习成功。</dd></div>
              <div><dt>仍有未解决问题</dt><dd>本题结束并记录待复核，可回看核验理由和解析。</dd></div>
              <div><dt>达到支持上限</dt><dd>本轮支持结束；题目有完整解析时，页面会展示解析。</dd></div>
            </dl>
            <figure class="guide-shot" data-screenshot="10">
              <div class="guide-shot-space"><span class="guide-shot-number">10</span><div><strong>完整解析与理解确认</strong><span>截图待补充</span></div></div>
              <figcaption>图 10 · 解析内容及理解确认按钮。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="11">
              <div class="guide-shot-space"><span class="guide-shot-number">11</span><div><strong>掌握度核验与结果</strong><span>截图待补充</span></div></div>
              <figcaption>图 11 · 核验问题、回答位置与结果说明。</figcaption>
            </figure>
          </section>

          <section id="speech" class="guide-section" aria-labelledby="speech-title">
            <h3 id="speech-title"><span>1.9</span>收听回复与设置音色</h3>
            <p>老师回复生成后，点击<span class="guide-control">播放语音</span>收听，再次点击可暂停。浏览器阻止自动播放时，手动点击播放即可。</p>
            <h4>自动播放与个人音色</h4>
            <ol>
              <li>点击顶部齿轮形的<span class="guide-control">设置</span>按钮。</li>
              <li>按需要开启或关闭<span class="guide-control">自动播放老师回复</span>。</li>
              <li>点击<span class="guide-control">设置音色</span>，按学段、学科、性别或名字筛选。</li>
              <li>选择音色后点击<span class="guide-control">保存个人音色</span>，再播放老师回复。</li>
            </ol>
            <p class="guide-note">个人音色仅对当前账号生效。</p>
            <figure class="guide-shot" data-screenshot="12">
              <div class="guide-shot-space"><span class="guide-shot-number">12</span><div><strong>老师语音播放入口</strong><span>截图待补充</span></div></div>
              <figcaption>图 12 · 播放和暂停语音的按钮。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="13">
              <div class="guide-shot-space"><span class="guide-shot-number">13</span><div><strong>自动播放与老师音色设置</strong><span>截图待补充</span></div></div>
              <figcaption>图 13 · 自动播放开关、音色筛选和保存入口。</figcaption>
            </figure>
          </section>

          <section id="history" class="guide-section" aria-labelledby="history-title">
            <h3 id="history-title"><span>1.10</span>回看记录与重新自讲</h3>
            <p>自讲页面下方的<span class="guide-control">历史记录</span>按时间呈现本轮提交、AI 反馈和核验结果，适合对照前后的思路变化。</p>
            <ul>
              <li>查看其他会话：打开顶部<span class="guide-control">菜单</span>，选择<span class="guide-control">自讲历史</span>，点击一条记录进入对应会话。</li>
              <li>继续当前自讲：留在当前会话，根据已有反馈继续完成学习。</li>
              <li>重新开始：从顶部菜单选择<span class="guide-control">重新自讲</span>，开启新一轮自讲。</li>
            </ul>
            <p>自讲历史展示当前账号的会话，并标注进行中、已完成、已暂停或待复核等状态。</p>
            <p class="guide-note">重新自讲前，先回顾需要的记录。被替换的进行中会话不会继续出现在自讲历史列表中。</p>
            <figure class="guide-shot" data-screenshot="14">
              <div class="guide-shot-space"><span class="guide-shot-number">14</span><div><strong>本轮历史记录</strong><span>截图待补充</span></div></div>
              <figcaption>图 14 · 学生提交、AI 反馈与核验记录。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="15">
              <div class="guide-shot-space"><span class="guide-shot-number">15</span><div><strong>自讲历史与重新自讲</strong><span>截图待补充</span></div></div>
              <figcaption>图 15 · 顶部菜单和历史会话列表。</figcaption>
            </figure>
          </section>
        </section>

        <section class="guide-group guide-teacher-group" aria-labelledby="teacher-title">
          <header class="guide-group-heading">
            <span class="guide-group-number" aria-hidden="true">02</span>
            <div><p class="guide-eyebrow">教师专用</p><h2 id="teacher-title">管理题目与查看运行过程</h2><p>使用教师账号维护题目材料，并结合运行日志查看一次自讲的具体过程。</p></div>
          </header>

          <section id="question-details" class="guide-section" aria-labelledby="question-details-title">
            <h3 id="question-details-title"><span>2.1</span>题目详情与评价材料</h3>
            <p>在题目列表点击<span class="guide-control">查看</span>，手机端点击<span class="guide-control">查看详情</span>，进入题目详情页。</p>
            <p>这里可以查看题干、标准答案、关键评分点、常见错误、可接受的其他解法、分层提示、提示子问题和完整解析。</p>
            <dl class="guide-definitions">
              <div><dt>完整评分</dt><dd>题目已填写关键评分点，评价时使用这些材料。</dd></div>
              <div><dt>基础评价</dt><dd>没有关键评分点，但已提供标准答案或完整解析。</dd></div>
              <div><dt>通用评价</dt><dd>尚未提供关键评分点、标准答案及完整解析，按通用方式评价。</dd></div>
            </dl>
            <p>通过详情页的<span class="guide-control">开始自讲</span>或<span class="guide-control">重新自讲</span>体验题目，也可以点击<span class="guide-control">编辑题目</span>补充材料。</p>
            <figure class="guide-shot" data-screenshot="18">
              <div class="guide-shot-space"><span class="guide-shot-number">18</span><div><strong>题目详情</strong><span>截图待补充</span></div></div>
              <figcaption>图 18 · 评价材料、评价方式和详情页操作入口。</figcaption>
            </figure>
          </section>

          <section id="question-editor" class="guide-section" aria-labelledby="question-editor-title">
            <h3 id="question-editor-title"><span>2.2</span>录入与编辑题目</h3>
            <p>在题目列表点击<span class="guide-control">录入题目</span>新建题目；已有题目从详情页点击<span class="guide-control">编辑题目</span>。</p>
            <ol>
              <li>填写必填的<span class="guide-control">题目内容</span>，按需补充标准答案。</li>
              <li>在“评价材料”中填写关键评分点、常见错误和可接受的其他解法，使用新增或删除按钮调整条目。</li>
              <li>在“学习引导”中按从轻到重的顺序填写分层提示，按需提供提示子问题。</li>
              <li>填写完整解析，点击<span class="guide-control">保存题目</span>。如有表单提示，按提示修改后保存。</li>
            </ol>
            <p>题目内容必填，其余材料可以逐步补充。保存后查看题目详情，再进入自讲，体验这道题的评价与引导。</p>
            <figure class="guide-shot" data-screenshot="19">
              <div class="guide-shot-space"><span class="guide-shot-number">19</span><div><strong>题目与答案录入</strong><span>截图待补充</span></div></div>
              <figcaption>图 19 · 题目内容、标准答案和保存入口。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="20">
              <div class="guide-shot-space"><span class="guide-shot-number">20</span><div><strong>评价材料与学习引导</strong><span>截图待补充</span></div></div>
              <figcaption>图 20 · 评分点、分层提示及各类条目的增删操作。</figcaption>
            </figure>
          </section>

          <section id="archive" class="guide-section" aria-labelledby="archive-title">
            <h3 id="archive-title"><span>2.3</span>归档与恢复题目</h3>
            <p>不再用于当前测试的题目，可在题目列表点击<span class="guide-control">归档</span>，或在详情页点击<span class="guide-control">归档题目</span>。</p>
            <ul>
              <li>归档后，题目不再出现在普通可用题目列表中，也不能从列表开始新的自讲。</li>
              <li>需要查找归档题目时，打开列表中的<span class="guide-control">显示已归档</span>。</li>
              <li>点击<span class="guide-control">恢复</span>或详情页的<span class="guide-control">恢复题目</span>，让题目重新用于自讲。</li>
            </ul>
            <figure class="guide-shot" data-screenshot="21">
              <div class="guide-shot-space"><span class="guide-shot-number">21</span><div><strong>归档与恢复操作</strong><span>截图待补充</span></div></div>
              <figcaption>图 21 · “显示已归档”开关、归档和恢复入口。</figcaption>
            </figure>
          </section>

          <section id="logs" class="guide-section" aria-labelledby="logs-title">
            <h3 id="logs-title"><span>2.4</span>查看运行日志</h3>
            <p>在自讲页面打开顶部<span class="guide-control">菜单</span>，点击<span class="guide-control">查看运行日志</span>，进入当前会话的运行轨迹。</p>
            <ol>
              <li>通过“运行”选择某一次运行，或选择<span class="guide-control">全部运行</span>。</li>
              <li>选择<span class="guide-control">等宽</span>查看事件顺序，或选择<span class="guide-control">按时长</span>查看时间分布。</li>
              <li>查看上下文、用户与助手记录；需要更多信息时，切换<span class="guide-control">显示完整日志</span>，查看状态变化和模型请求等记录。</li>
              <li>通过搜索框查找记录类型、摘要或序号，按需展开、收起记录。</li>
            </ol>
            <p>查看完成后，点击<span class="guide-control">返回会话</span>回到自讲页面。</p>
            <figure class="guide-shot" data-screenshot="22">
              <div class="guide-shot-space"><span class="guide-shot-number">22</span><div><strong>运行轨迹与工具栏</strong><span>截图待补充</span></div></div>
              <figcaption>图 22 · 运行选择、时间显示、日志范围和搜索入口。</figcaption>
            </figure>
            <figure class="guide-shot" data-screenshot="23">
              <div class="guide-shot-space"><span class="guide-shot-number">23</span><div><strong>展开的日志记录</strong><span>截图待补充</span></div></div>
              <figcaption>图 23 · 一条上下文、模型请求或助手回复的详细内容。</figcaption>
            </figure>
          </section>
        </section>

        <footer class="guide-footer"><span>AI 自讲 · 使用指南</span><a href="#guide-top">返回顶部 <span aria-hidden="true">↑</span></a></footer>
      </div>
    </div>
  </main>
</template>

<style scoped>
.usage-guide {
  color: var(--color-text-primary, #333333);
  background:
    radial-gradient(ellipse 800px 500px at 0 0, rgb(183 40 255 / 18%), transparent 75%),
    radial-gradient(ellipse 700px 480px at 100% 0, rgb(85 217 255 / 12%), transparent 70%),
    linear-gradient(180deg, var(--color-shell-base, #36236e), var(--color-shell-deep, #22134f) 850px);
  padding: 40px 32px 64px;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif;
  font-size: 16px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.usage-guide *, .usage-guide *::before, .usage-guide *::after { box-sizing: border-box; }
.usage-guide a { text-decoration: none; transition: color 180ms ease, background-color 180ms ease; }
.usage-guide a:focus-visible, .usage-guide summary:focus-visible { outline: 3px solid #1d4ed8; outline-offset: 4px; border-radius: 5px; }
.usage-guide a { color: var(--color-brand-700, #1d4ed8); }
.usage-guide a:hover { text-decoration: underline; text-underline-offset: 4px; }
.usage-guide p { margin: 0 0 14px; }
.usage-guide h1, .usage-guide h2, .usage-guide h3, .usage-guide h4 { color: inherit; font-weight: 700; }
.usage-guide h1 { font-size: clamp(28px, 3vw, 38px); line-height: 1.3; letter-spacing: -.025em; margin: 10px 0 20px; }
.usage-guide h2 { font-size: 25px; line-height: 1.45; margin: 0 0 10px; }
.usage-guide h3 { display: flex; align-items: baseline; gap: 13px; font-size: 21px; line-height: 1.55; margin: 0 0 20px; }
.usage-guide h3 > span { flex-shrink: 0; color: var(--color-brand-700, #1d4ed8); font-size: 14px; font-weight: 600; }
.usage-guide h4 { font-size: 16px; margin: 24px 0 8px; }
.guide-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); align-items: start; gap: 32px; max-width: 1200px; margin: 0 auto; }
.guide-sidebar { position: fixed; top: 108px; width: 230px; max-height: calc(100dvh - 132px); overflow-y: auto; padding: 0 12px 12px 0; scrollbar-width: thin; scrollbar-color: #76659f transparent; }
.usage-guide .guide-home { display: flex; align-items: center; gap: 12px; color: #ffffff; font-size: 18px; font-weight: 700; margin-bottom: 24px; }
.guide-mark { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 13px; background: var(--gradient-action, linear-gradient(90deg, #a321e8, #2563eb)); }
.guide-home-caption { display: block; color: #d3cbea; font-size: 12px; font-weight: 400; letter-spacing: .12em; }
.usage-guide .guide-nav-label { margin: 24px 0 10px 12px; font-size: 12px; color: #d3cbea; font-weight: 600; letter-spacing: .06em; }
.guide-sidebar nav > a { display: flex; align-items: center; min-height: 44px; padding: 8px 12px; border-radius: 10px; color: #eee9ff; font-size: 14px; line-height: 1.6; }
.guide-sidebar nav > a:hover { background: rgb(255 255 255 / 10%); color: #ffffff; text-decoration: none; }
.guide-sidebar a:focus-visible { outline-color: #55d9ff; }
.usage-guide .guide-sidebar-note { padding: 18px 12px 0; margin: 20px 0 0; border-top: 1px solid rgb(255 255 255 / 16%); color: #d3cbea; font-size: 12px; line-height: 1.9; }
.guide-reader { grid-column: 2; min-width: 0; padding: 48px; background: var(--color-surface, #ffffff); border: 1px solid rgb(255 255 255 / 45%); border-radius: 24px; box-shadow: 0 18px 60px rgb(14 6 39 / 16%); }
.guide-intro { padding-bottom: 36px; }
.usage-guide .guide-eyebrow { margin: 0 0 8px; color: var(--color-brand-700, #1d4ed8); font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.guide-lead { color: var(--color-text-secondary, #666666); max-width: 44em; }
.guide-shortcuts { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 24px; }
.guide-shortcuts a { display: inline-flex; align-items: center; justify-content: center; gap: 14px; min-height: 44px; padding: 10px 18px; border-radius: 12px; border: 1px solid var(--color-border, #e6e6ec); font-size: 14px; font-weight: 600; }
.usage-guide .guide-primary-link { background: var(--gradient-action, linear-gradient(90deg, #a321e8, #2563eb)); border-color: transparent; color: #ffffff; }
.usage-guide .guide-primary-link:hover { background: var(--gradient-action-hover, linear-gradient(90deg, #931ccf, #1d4ed8)); text-decoration: none; }
.guide-shortcuts a:not(.guide-primary-link):hover { background: #eef4ff; text-decoration: none; }
.guide-mobile-directory { display: none; }
.guide-group-heading { display: flex; align-items: flex-start; gap: 20px; padding: 28px; border-radius: 16px; background: #eef4ff; }
.guide-group-heading p:last-child { margin: 0; color: var(--color-text-secondary, #666666); font-size: 14px; }
.guide-group-number { flex-shrink: 0; color: var(--color-brand-700, #1d4ed8); border-top: 3px solid #55d9ff; padding-top: 5px; font-size: 30px; line-height: 1.2; font-weight: 700; }
.guide-teacher-group { margin-top: 48px; }
.guide-teacher-group .guide-group-heading { background: #f6f2ff; }
.guide-section { padding: 36px 0; border-bottom: 1px solid var(--color-border, #e6e6ec); scroll-margin-top: 104px; }
.guide-section:target > h3 { color: var(--color-brand-700, #1d4ed8); }
.guide-section ul, .guide-section ol { padding-left: 24px; margin: 16px 0; }
.guide-section li { padding-left: 4px; margin: 10px 0; }
.guide-section li::marker { color: var(--color-brand-700, #1d4ed8); font-weight: 600; }
.guide-control { display: inline; padding: 2px 5px; border: 1px solid #e6e6ec; border-radius: 5px; color: #333333; background: #f5f5f5; font-size: .9em; -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.usage-guide .guide-note { margin: 20px 0; padding: 14px 18px; border-left: 3px solid #2870ff; border-radius: 0 10px 10px 0; background: #eef4ff; color: #333333; font-size: 14px; }
.guide-definitions { margin: 20px 0; }
.guide-definitions > div { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 16px; padding: 13px 0; border-bottom: 1px solid #e6e6ec; }
.guide-definitions dt { font-weight: 600; }
.guide-definitions dd { margin: 0; color: #666666; }
.usage-guide .guide-formula { padding: 16px 20px; background: #f6f2ff; border-radius: 10px; color: #54309a; font-weight: 600; }
.guide-input-methods { margin: 24px 0; padding: 4px 20px; border: 1px solid #e6e6ec; border-radius: 14px; }
.guide-input-methods > div + div { border-top: 1px solid #e6e6ec; }
.guide-input-methods h4 { margin-top: 16px; }
.guide-shot { margin: 24px 0 8px; }
.guide-shot-space { display: flex; align-items: center; justify-content: center; gap: 20px; min-height: 136px; padding: 24px; border: 1px dashed #9cabc6; border-radius: 12px; background: #f8faff; }
.guide-shot-number { display: grid; place-items: center; flex-shrink: 0; width: 44px; height: 44px; border: 1px solid #d1dcf1; border-radius: 12px; color: #1d4ed8; background: #eef4ff; font-size: 14px; font-weight: 600; }
.guide-shot-space strong { display: block; color: #4d5670; font-size: 14px; font-weight: 500; }
.guide-shot-space div > span { display: block; color: #666666; font-size: 12px; margin-top: 3px; }
.guide-shot img { display: block; width: 100%; height: auto; border: 1px solid #e6e6ec; border-radius: 12px; }
.guide-shot figcaption { margin-top: 8px; font-size: 12px; color: #666666; line-height: 1.8; }
.guide-footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding-top: 32px; color: #666666; font-size: 12px; }
.guide-footer a { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 8px; }
.guide-skip { position: fixed; left: 24px; top: -100px; z-index: 100; background: #ffffff; color: #1d4ed8; border: 2px solid #1d4ed8; padding: 12px 18px; border-radius: 8px; }
.guide-skip:focus { top: 12px; }
#guide-content, #guide-top { scroll-margin-top: 96px; }
@media (max-width: 1100px) {
  .usage-guide { padding: 28px 24px 48px; }
  .guide-layout { grid-template-columns: 206px minmax(0, 1fr); gap: 24px; }
  .guide-sidebar { width: 206px; }
  .guide-reader { padding: 32px; }
}
@media (max-width: 959px) {
  .guide-layout { display: block; max-width: 820px; }
  .guide-sidebar { display: none; }
  .guide-mobile-directory { display: block; margin-top: 28px; border: 1px solid #e6e6ec; border-radius: 12px; }
  .guide-mobile-directory summary { padding: 12px 16px; min-height: 48px; cursor: pointer; font-size: 14px; font-weight: 600; }
  .guide-mobile-directory summary > span { margin-left: 10px; color: #666666; font-size: 12px; font-weight: 400; }
  .guide-mobile-directory nav { padding: 0 12px 12px; }
  .guide-mobile-directory nav a { display: flex; align-items: center; min-height: 44px; padding: 8px 10px; font-size: 14px; border-radius: 8px; }
  .guide-mobile-directory nav a:hover { background: #eef4ff; }
  .usage-guide .guide-mobile-directory .guide-nav-label { color: #666666; margin: 14px 10px 6px; }
}
@media (max-width: 600px) {
  .usage-guide { padding: 20px 12px 32px; }
  .guide-reader { padding: 28px 20px; border-radius: 16px; }
  .usage-guide h1 { font-size: 28px; }
  .usage-guide h2 { font-size: 21px; }
  .usage-guide h3 { gap: 10px; font-size: 19px; }
  .guide-intro { padding-bottom: 28px; }
  .guide-shortcuts { gap: 10px; }
  .guide-shortcuts a { padding: 10px 12px; gap: 8px; }
  .guide-group-heading { padding: 20px 16px; gap: 14px; }
  .guide-group-number { font-size: 24px; }
  .guide-section { padding: 28px 0; }
  .guide-definitions > div { grid-template-columns: 1fr; gap: 4px; }
  .guide-shot-space { min-height: 120px; padding: 20px 14px; gap: 14px; }
  .guide-footer { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  .usage-guide a { transition: none; }
}
@media print {
  .usage-guide { padding: 0; background: #ffffff; font-size: 12pt; }
  .guide-layout { display: block; }
  .guide-sidebar, .guide-mobile-directory, .guide-shortcuts, .guide-footer, .guide-skip { display: none; }
  .guide-reader { border: 0; padding: 0; box-shadow: none; }
  .guide-shot { break-inside: avoid; }
  .guide-section h3 { break-after: avoid; }
}
</style>
