# Frozen SketchUp worker. Loaded with -RubyStartup in a newly owned process only.
require 'json'
require 'digest'

module TaskRelaySketchup
  def self.write(path, value)
    bytes = JSON.generate(value)
    raise 'Snapshot/output exceeds 1.5 MB' if bytes.bytesize > 1_500_000
    temporary = path + '.tmp'
    File.open(temporary, 'wx') { |f| f.write(bytes); f.flush; f.fsync }
    File.rename(temporary, path)
  end

  def self.vector(value)
    value.to_a.map { |v| v.to_f.round(8) }
  end

  def self.attributes(object)
    result = {}
    return result unless object.respond_to?(:attribute_dictionaries) && object.attribute_dictionaries
    object.attribute_dictionaries.each do |dictionary|
      result[dictionary.name] = {}
      dictionary.each_pair { |key, value| result[dictionary.name][key] = scalar(value) }
    end
    result
  end

  def self.scalar(value)
    case value
    when NilClass, TrueClass, FalseClass, String, Integer then value
    when Float
      raise 'Nonfinite document value' unless value.finite?
      value.round(8)
    when Array then value.map { |v| scalar(v) }
    when Geom::Point3d, Geom::Vector3d, Geom::Transformation then vector(value)
    when Sketchup::Color then value.to_a
    when Length then value.to_f.round(8)
    else raise "Unsupported document value: #{value.class}"
    end
  end

  def self.camera(camera)
    result = { 'eye'=>vector(camera.eye), 'target'=>vector(camera.target), 'up'=>vector(camera.up),
               'perspective'=>camera.perspective? }
    result['projection'] = camera.perspective? ? camera.fov : camera.height.to_f
    result
  end

  def self.named_options(options)
    result = {}
    options.each_pair { |key, value| result[key] = scalar(value) }
    result
  end

  def self.material_name(material)
    material ? material.name : nil
  end

  def self.entity(entity, stack, budget)
    budget[0] += 1
    raise 'Model exceeds 5000 total entities or nesting depth 32' if budget[0] > 5000 || stack.length > 32
    raise 'Invalid entity' unless entity.valid?
    type = entity.typename
    bounds = entity.bounds
    value = { 'type'=>type, 'hidden'=>entity.hidden?, 'layer'=>entity.layer.name,
              'material'=>material_name(entity.material), 'attributes'=>attributes(entity),
              'bounds'=>[vector(bounds.min),vector(bounds.max)] }
    case entity
    when Sketchup::Edge
      value['vertices'] = [vector(entity.start.position),vector(entity.end.position)]
      value['soft'] = entity.soft?; value['smooth'] = entity.smooth?
      budget[1] += 2
    when Sketchup::Face
      value['loops'] = entity.loops.map { |loop| loop.vertices.map { |v| vector(v.position) } }
      value['back_material'] = material_name(entity.back_material)
      budget[1] += value['loops'].sum(&:length)
    when Sketchup::Group, Sketchup::ComponentInstance
      definition = entity.definition
      raise 'Recursive component definition' if stack.include?(definition.object_id)
      raise 'External component definitions are outside this contract' unless definition.path.to_s.empty?
      value['name'] = entity.name
      value['locked'] = entity.locked?
      value['transform'] = vector(entity.transformation)
      value['definition_attributes'] = attributes(definition)
      value['definition_name'] = definition.name
      value['dimensions_mm'] = [bounds.width,bounds.height,bounds.depth].map { |n| (n.to_f*25.4).round(6) }
      value['children'] = definition.entities.map { |child| [child.persistent_id.to_s, self.entity(child,stack+[definition.object_id],budget)] }.to_h
    else raise "Unsupported SketchUp entity: #{type}"
    end
    raise 'Model exceeds 100000 geometry points' if budget[1] > 100_000
    value
  end

  def self.snapshot(model)
    materials = {}
    model.materials.each do |material|
      raise 'Textured materials are outside the SketchUp v1 contract' if material.texture
      materials[material.name] = { 'color'=>material.color.to_a, 'alpha'=>material.alpha, 'attributes'=>attributes(material) }
    end
    tags = model.layers.map { |layer| [layer.name, { 'visible'=>layer.visible?, 'color'=>layer.color.to_a, 'attributes'=>attributes(layer) }] }.to_h
    scenes = model.pages.map { |page| [page.name, { 'camera'=>camera(page.camera), 'attributes'=>attributes(page) }] }.to_h
    options = model.options.map { |provider| [provider.name,named_options(provider)] }.to_h
    budget = [0,0]
    entities = model.entities.map { |e| [e.persistent_id.to_s,entity(e,[],budget)] }.to_h
    { 'entities'=>entities, 'document'=>{ 'materials'=>materials,'tags'=>tags,'scenes'=>scenes,
      'options'=>options,'attributes'=>attributes(model),'camera'=>camera(model.active_view.camera) },
      'total_entities'=>budget[0], 'geometry_points'=>budget[1], 'sketchup_version'=>Sketchup.version }
  end

  def self.open_model(path)
    raise 'SketchUp could not open the exact model' unless Sketchup.open_file(path)
    model = Sketchup.active_model
    raise 'Opened model path differs from request' unless File.realpath(model.path) == File.realpath(path)
    model
  end

  def self.perform(request)
    mode = request.fetch('mode'); out = request.fetch('out')
    return { 'sketchup_version'=>Sketchup.version, 'ruby_version'=>RUBY_VERSION } if mode == 'startup'
    model = if mode == 'verify'
      open_model(File.join(out,'candidate.skp'))
    elsif request['source']
      open_model(request['source'])
    else
      raise 'Cannot initialize a new SketchUp model' unless Sketchup.file_new
      fresh = Sketchup.active_model
      fresh.entities.clear!
      fresh.definitions.purge_unused
      fresh.materials.purge_unused
      fresh
    end
    if mode == 'before'
      RubyVM::InstructionSequence.compile(File.read(request.fetch('script'),encoding:'UTF-8'))
      write(request.fetch('snapshot'),snapshot(model))
    elsif mode == 'inspect'
      write(request.fetch('snapshot'),snapshot(model))
    elsif mode == 'model'
      # No sandbox claim: this is the exact host-approved Ruby script.
      source = File.read(request.fetch('script'),encoding:'UTF-8')
      model.start_operation('Task Relay candidate', true)
      begin
        eval(source, binding, request.fetch('script'))
        raise 'Script switched the active document' unless Sketchup.active_model == model
        model.commit_operation
      rescue Exception
        model.abort_operation
        raise
      end
      candidate = File.join(out,'candidate.skp')
      raise 'SketchUp failed to save candidate' unless model.save(candidate)
      return { 'candidate_sha256'=>Digest::SHA256.file(candidate).hexdigest }
    elsif mode == 'verify'
      write(request.fetch('snapshot'),snapshot(model))
      checks = JSON.parse(File.read(request.fetch('checks')))
      resolution = checks.fetch('preview').fetch('resolution')
      view = model.active_view
      view.zoom_extents
      view.refresh
      raise 'SketchUp failed to write preview' unless view.write_image(filename:File.join(out,'preview.png'),
        width:resolution[0],height:resolution[1],antialias:true,transparent:false)
    else
      raise 'Unknown SketchUp worker mode'
    end
    result = { 'snapshot_sha256'=>Digest::SHA256.file(request.fetch('snapshot')).hexdigest }
    result['candidate_sha256'] = Digest::SHA256.file(File.join(out,'candidate.skp')).hexdigest if mode == 'verify'
    result
  end

  def self.start(path)
    request = JSON.parse(File.read(path))
    stem = path.sub(/\.json\z/,'')
    began = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    timer = nil
    timer = UI.start_timer(0.1,true) do
      next unless File.exist?(stem+'.owner.json') || Process.clock_gettime(Process::CLOCK_MONOTONIC)-began > 10
      UI.stop_timer(timer)
      # Never terminate or mutate an application until ownership is established.
      owner = JSON.parse(File.read(stem+'.owner.json'))
      raise 'SketchUp process ownership mismatch' unless owner == { 'pid'=>Process.pid, 'token'=>request.fetch('token') }
      identity = { 'pid'=>Process.pid, 'token'=>request.fetch('token'), 'mode'=>request.fetch('mode') }
      begin
        write(stem+'.started.json',identity)
        details = perform(request)
        write(stem+'.result.json',identity.merge('passed'=>true,'details'=>details))
        # This is a dedicated disposable process; no user session is attached.
        Kernel.exit!(0)
      rescue Exception => error
        write(stem+'.result.json',identity.merge('passed'=>false,'error'=>"#{error.class}: #{error.message}\n#{error.backtrace&.first(8)&.join("\n")}"))
        Kernel.exit!(1)
      end
    end
  end
end
