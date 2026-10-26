# 文字环绕与混合字体对齐

用于段落前缀标签、摘要与来源混排，以及中文名称、数字字体、图标和按钮的对齐。方案不依赖具体业务、项目结构或组件名称。只调整排版，不改变内容、加载、点击或状态切换逻辑。

## 当前主方案

需要不同字号的标签、正文和来源文字视觉居中，同时保留自然换行时：

1. 段落保留普通行内排版，正文明确包在 `display: inline` 的元素中。
2. 标签、正文元素和来源入口三个行内参与者都设置 `vertical-align: middle`。不要只改标签，留下正文的默认 baseline。
3. 标签内部用 `inline-flex` 双轴居中，文字行高按标签实际高度设置。来源文字与图标同样组成一个 `inline-flex` 单元。
4. 移除这组参与者上旧的 `margin-top`、`top` 和 `translateY` 补偿，避免重复校准。

`vertical-align` 负责不同参与者之间的对齐；`align-items`、`justify-content` 负责组件内部对齐。只在段落父容器设置 `vertical-align`，或只给标签内部设置 `align-items: center`，都不能替代三个行内参与者的统一对齐。

## 先区分三个对齐层次

| 目标                                 | 对齐方法                                                           | 注意事项                                    |
| ------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------- |
| 标签、正文、来源在同一段落中自然换行 | 正文使用行内 `span`，标签和来源使用 `inline-flex`                  | 不把整个段落改成 flex，不给正文建立独立一列 |
| 标签与正文首行文字居中对齐           | 标签、正文、来源统一设置 `vertical-align: middle`                  | 只给标签设置居中、正文仍用 baseline 不够    |
| 标签内部或一行里的不同字体、图标居中 | 标签内部 flex 双轴居中；固定高度的名称行使用 `align-items: center` | 盒子居中不等于不同字体的字面天然居中        |

## 1. 段落采用自然行内环绕

标签、摘要、来源可以采用下面的段落结构。类名仅用于表达排版职责，可按目标项目约定替换：

```html
<p class="event-text">
  <span class="event-text__tag">
    <span class="event-text__tag-text">标签</span>
  </span>
  <span class="event-text__summary">这里是可以自然换行的摘要内容。</span>
  <span class="event-text__source">
    <span>来源+1</span>
    <svg
      class="event-text__source-icon"
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
    >
      <path d="M5 2L10 7L5 12" stroke="currentColor" />
    </svg>
  </span>
</p>
```

```scss
.event-text {
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  word-break: break-word;

  &__tag {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    min-width: 32px;
    height: 20px;
    margin-right: 6px;
    padding: 0 4px;
    vertical-align: middle;

    &-text {
      font-size: 12px;
      font-weight: 500;
      line-height: 20px;
      white-space: nowrap;
    }
  }

  &__summary {
    display: inline;
    vertical-align: middle;
  }

  &__source {
    display: inline-flex;
    align-items: center;
    margin-left: 6px;
    font-size: 14px;
    line-height: 22px;
    vertical-align: middle;
    white-space: nowrap;

    &-icon {
      display: block;
      flex: none;
      width: 14px;
      height: 14px;
      margin-left: 2px;
    }
  }
}
```

- 正文的 `span` 保持默认 `display: inline`。首行接在标签后，后续行回到段落左边缘，使用整行宽度。
- 标签是不可拆分的行内盒子。摘要和来源继续参与同一段落的换行。
- 来源文字和图标作为一个单元换行，避免箭头单独掉到下一行。图标在单元内部居中，间距用 margin。
- 不用 `display: flex`、grid 或给摘要设置 `inline-block` 来模拟这种环绕；这些写法会改变正文的换行边界。
- 带强调前缀的正文同样可以使用 `<p><b>标签</b> 正文</p>`。强调文字直接留在段落内，不拆成固定标签列和正文列。

## 2. 标签外部对齐与内部居中分开处理

段落负责行内对齐，标签组件负责内部居中。项目已提供等价样式工具或 mixin 时直接复用；不存在时按下述结构实现，不依赖特定目录或组件。

### 外部：先确认设计对齐方式

以标签高 20px、正文行高 22px 为例。转为自然行内排版后，仅设置标签的 `vertical-align: top` 或按高度差补 `margin-top`，仍不能保证不同字号的文字中心一致。

将标签、正文 `span`、来源入口统一设置为 `vertical-align: middle`，让三个行内盒子使用同一条对齐线。正文继续使用 `display: inline`，后续行仍从段落左侧开始。只改标签、不改正文的默认 baseline，会保留相对偏差。

不要叠加旧的顶部补偿、固定 `top` 或文字 `translateY`。先确认三者的对齐方式一致，再分别核对标签内部居中和字体实际渲染。

### 内部：两种已用方案

**行内标签**使用 `inline-flex + align-items: center + justify-content: center`。内部文字单独包一层。示例使用 12px 字号、20px 行高、500 字重，字体沿用目标页面的中文字体与系统回退栈。

先还原字体、字号、字重、行高、容器高度和 padding，再判断视觉偏移。不要只因文字 Range 与容器中心不同，就直接增加 `translateY`；Range 边界不等于实际字形墨迹边界。若设计中的文字行高等于标签高度，按实际值设置，不用 `line-height: 1` 再靠临时位移补偿。

示例尺寸：正文 15px / 22px，标签 12px / 20px、最小宽 32px、左右 padding 4px、圆角 2px；来源文字 14px / 22px、颜色 `#999`，箭头 SVG 为 14px，文字与箭头间距 2px。状态标签可以分别使用浅红底/红字、浅绿底/绿字；灰色标签可使用 `#e0e0e0` / `#666`。具体颜色优先使用目标项目的设计变量，并检查与容器底色的区分度。

**小字号标签的内部居中备选**可以采用 padding 方案。下面演示的是另一个明确要求外框按首行顶边补偿的场景，不替代当前主方案：

```scss
@mixin badge-text-center($height, $font-size, $padding-x) {
  display: inline-block;
  box-sizing: border-box;
  height: $height;
  padding: ($height - $font-size) * 0.5 $padding-x;
  font-size: $font-size;
  line-height: $font-size;
  white-space: nowrap;
  text-align: center;
}

@mixin inline-flow-badge-align($line-height, $badge-height, $margin-right) {
  vertical-align: top;
  margin-top: calc((#{$line-height} - #{$badge-height}) / 2);
  margin-right: $margin-right;
}

.reference-headline {
  margin: 0;
  line-height: 22px;

  &__tag {
    @include badge-text-center(18px, 10px, 4px);
    @include inline-flow-badge-align(22px, 18px, 4px);
  }
}
```

`badge-text-center` 使用 `inline-block`、`box-sizing: border-box`、固定高度、与字号相同的行高及 `text-align: center`。上下 padding 为 `(标签高度 - 字号) / 2`。本例为 4px，左右 padding 也为 4px。

这套方案可用于处理目标 WebView 上的 inline-flex 字体基线偏移，不代表所有标签都必须换成 padding。标签内部由 padding 居中，外部首行位置由第二个 mixin 负责。复用已有 mixin 时检查调用顺序，避免内部居中样式中的 `vertical-align` 覆盖外部对齐方式。

`inline-flow-badge-align` 采用 `vertical-align: top` 加 `calc((正文行高 - 标签高度) / 2)` 的顶部补偿。它与段落三者统一 middle 的方案不同。按实际排版目标选择，不在同一标签上叠加两套外部对齐方式。

## 3. 中文、数字字体与图标使用共同的行容器

名称行可以固定为 28px，使用 `display: flex; align-items: center`。中文名称、数字、角标、操作图标分别作为子项。

```scss
.name-row {
  display: flex;
  align-items: center;
  height: 28px;
  min-width: 0;

  &__name {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    font-size: 18px;
    line-height: 28px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__number {
    flex-shrink: 0;
    margin-left: 2px;
    font-family: NumericFont, sans-serif;
    font-size: 18px;
    white-space: nowrap;
  }

  &__action {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    margin-left: 6px;
    line-height: 0;
  }
}
```

- `align-items: center` 对齐各子项的盒子中心。图标或标签内部用 `justify-content: center` 控制水平居中，不把整行名称强行居中。
- 长名称只压缩名称本身。数字、标签和图标不收缩，避免长名称把按钮挤扁。
- `NumericFont` 是示例字体别名，接入时替换为项目已有的数字字体。数字与中文字体的 ascent、descent 不同，同字号、同容器中心仍可能有视觉偏差。先固定行高、字体和盒子尺寸，再检查字面位置。
- 小字号辅助代码可以使用 `line-height: 1`，必要时对其局部校准，例如 `translateY(2px)`。像素值仅表示某种字体组合下的校准示例，不是不同字体或平台的通用偏移；只有复测确认需要时才使用。
- 间距使用 margin。不要为了对齐引入低版本 Android WebView 不支持的 flex gap。

## 4. 保留需要基线对齐的场景

辅助标题与关联项列表需要按文字基线排列时，容器使用 `align-items: baseline`。右侧列表以 `inline-block` 按钮自然换行，按钮内名称和数值留在同一行。

这与固定高度名称行的视觉居中目标不同。不要把页面中的 `baseline` 全部替换成 `center`。列表容器使用 `font-size: 0` 消除行内按钮之间的空白时，子按钮和数值必须显式恢复字号、行高。

## 验证要点

- 同时检查标签、正文、来源三个实际参与者的 `vertical-align`；不要只检查标签的 flex 属性。确认旧的顶部偏移和 transform 补偿未残留。
- 分别检查标签内文字与标签框的居中、标签与正文首行文字的居中。两项不能用同一个盒子中心测量结果代替。
- 检查一行、两行和多行正文；后续行应回到段落左边缘，来源标识不重叠、不截断。
- 检查来源入口位于首行末尾、跨行边界和最后一行时的表现，文字和图标保持同组，正文仍自然环绕。
- 检查短标签、长标签、中文与数字混排；标签内部居中，标签外框不意外撑大正文行高。
- 检查长名称、省略号、小字号代码和图标；名称可以收缩，数字与操作图标保持尺寸。
- 在实际字体及字体回退下，分别检查 Android WebView 和 iOS；区分盒子偏移与字体字面偏移。
- px/rem 转换后核对行高、标签高度和偏移使用同一尺度。只做排版修复时，保留既有加载、失败回退及交互逻辑。

使用以上方案前，先检查目标项目是否已有等价组件或 mixin，再按实际字号、行高、字体和设计变量调整。示例尺寸和名称不作为项目约束，也不要求采用特定目录结构。
